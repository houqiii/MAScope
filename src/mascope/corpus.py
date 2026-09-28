import html
import json
import re
import sqlite3
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, value):
        self.parts.append(value)

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "div", "br", "li", "pre", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "div", "li", "pre", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")


def plain_text(value):
    parser = _Text()
    parser.feed(value)
    text = re.sub(r"[ \t]+", " ", "".join(parser.parts))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _posts(path):
    events = ElementTree.iterparse(path, events=("start", "end"))
    _, root = next(events)
    for event, element in events:
        if event == "end" and element.tag == "row":
            yield dict(element.attrib)
            root.clear()


def _owner(post, host):
    return {
        key: value
        for key, value in {
            "user_id": post.get("OwnerUserId"),
            "display_name": post.get("OwnerDisplayName"),
            "link": (
                f"https://{host}/users/{post['OwnerUserId']}"
                if post.get("OwnerUserId")
                else None
            ),
        }.items()
        if value is not None
    }


def accepted_pairs(posts, database, community, snapshot, rejected=None):
    host = community if community.endswith(".com") else community + ".com"
    database = Path(database)
    if database.exists():
        raise FileExistsError(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE questions (answer TEXT, payload TEXT)")
        connection.execute("CREATE INDEX answers ON questions (answer)")
        for post in _posts(posts):
            if post.get("PostTypeId") != "1" or not post.get("AcceptedAnswerId"):
                continue
            question = plain_text(post.get("Body", ""))
            tags = re.findall(r"<([^>]+)>", post.get("Tags", ""))
            if len(question.split()) < 80 or not tags:
                continue
            record = {
                "question_id": int(post["Id"]),
                "answer_id": int(post["AcceptedAnswerId"]),
                "question": question,
                "title": html.unescape(post.get("Title", "")),
                "tags": tags,
                "question_url": f"https://{host}/questions/{post['Id']}",
                "question_license": post.get("ContentLicense"),
                "question_creation_date": post.get("CreationDate"),
                "question_revision_date": post.get(
                    "LastEditDate", post.get("CreationDate")
                ),
                "question_attribution": _owner(post, host),
            }
            connection.execute(
                "INSERT INTO questions VALUES (?, ?)",
                (post["AcceptedAnswerId"], json.dumps(record)),
            )
        connection.commit()
        for post in _posts(posts):
            if post.get("PostTypeId") != "2":
                continue
            matches = connection.execute(
                "SELECT payload FROM questions WHERE answer = ?", (post["Id"],)
            ).fetchall()
            record = None
            for match in matches:
                candidate = json.loads(match[0])
                if str(candidate["question_id"]) == post.get("ParentId"):
                    record = candidate
                elif rejected is not None:
                    rejected.append(
                        {
                            "question_id": candidate["question_id"],
                            "answer_id": int(post["Id"]),
                            "reason": "accepted_answer_parent_mismatch",
                            "parent_id": post.get("ParentId"),
                        }
                    )
            if record is None:
                continue
            text = plain_text(post.get("Body", ""))
            if not text:
                continue
            yield {
                **record,
                "text": text,
                "accepted": True,
                "answer_score": int(post.get("Score", 0)),
                "source_url": f"https://{host}/a/{post['Id']}",
                "content_license": post.get("ContentLicense"),
                "creation_date": post.get("CreationDate"),
                "revision_date": post.get("LastEditDate", post.get("CreationDate")),
                "source_snapshot": snapshot,
                "attribution": _owner(post, host),
            }
    finally:
        connection.close()
