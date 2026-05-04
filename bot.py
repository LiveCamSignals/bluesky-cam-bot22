import os
import re
import sqlite3
import random
import logging
import requests
from datetime import datetime, timedelta
from atproto import Client, models

API_URL = "https://chaturbate.com/affiliates/api/onlinerooms/?format=json&wm=T2CSW"

BLUESKY_HANDLE = os.getenv("BLUESKY_HANDLE")
BLUESKY_PASSWORD = os.getenv("BLUESKY_PASSWORD")

DB_FILE = "posted.db"

logging.basicConfig(level=logging.INFO)

session = requests.Session()


# -----------------------------
# DATABASE
# -----------------------------

def init_db():

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS posted (
        username TEXT,
        last_post TEXT
    )
    """)

    conn.commit()
    conn.close()


def recently_posted(username):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(
        "SELECT last_post FROM posted WHERE username=?",
        (username,)
    )

    row = c.fetchone()

    conn.close()

    if not row:
        return False

    last = datetime.fromisoformat(row[0])

    return datetime.now() - last < timedelta(days=30)


def save_post(username):

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute(
        "INSERT INTO posted VALUES (?, ?)",
        (username, datetime.now().isoformat())
    )

    conn.commit()
    conn.close()


# -----------------------------
# TAG CLEANER
# -----------------------------

def clean_tag(tag):

    tag = tag.lower()
    tag = re.sub(r"[^a-z0-9]", "", tag)

    return tag


# -----------------------------
# BUILD HASHTAGS
# -----------------------------

def build_hashtags(room):

    tags = room.get("tags", [])

    cleaned = []

    for t in tags:

        tag = clean_tag(t)

        if tag and tag not in cleaned:
            cleaned.append(tag)

    cleaned = cleaned[:5]

    cleaned.extend(["LiveCams", "Chaturbate", "nsfw"])

    return cleaned


# -----------------------------
# FACETS
# -----------------------------

def build_facets(text, link, hashtags):

    facets = []

    def byte_range(sub):

        start = text.find(sub)

        if start == -1:
            return None

        start_byte = len(text[:start].encode("utf-8"))
        end_byte = start_byte + len(sub.encode("utf-8"))

        return models.AppBskyRichtextFacet.ByteSlice(
            byteStart=start_byte,
            byteEnd=end_byte
        )

    link_index = byte_range("Watch free")

    if link_index:

        facets.append(
            models.AppBskyRichtextFacet.Main(
                index=link_index,
                features=[models.AppBskyRichtextFacet.Link(uri=link)]
            )
        )

    for tag in hashtags:

        tag_text = f"#{tag}"

        idx = byte_range(tag_text)

        if idx:

            facets.append(
                models.AppBskyRichtextFacet.Main(
                    index=idx,
                    features=[models.AppBskyRichtextFacet.Tag(tag=tag)]
                )
            )

    return facets


# -----------------------------
# FETCH ROOMS
# -----------------------------

def fetch_rooms():

    logging.info("Fetching rooms")

    r = session.get(API_URL, timeout=20)

    r.raise_for_status()

    return r.json()


# -----------------------------
# NICHE FILTER
# -----------------------------

NICHES = {
    "bbw": ["bbw"],
    "milf": ["milf"],
    "asian": ["asian"],
    "latina": ["latina"],
    "ebony": ["ebony"]
}


def filter_rooms(rooms, niche):

    tags = NICHES[niche]

    results = []

    for r in rooms:

        if r.get("gender") != "f":
            continue

        if r.get("current_show") != "public":
            continue

        room_tags = [t.lower() for t in r.get("tags", [])]

        if not any(t in room_tags for t in tags):
            continue

        if recently_posted(r["username"]):
            continue

        results.append(r)

    results.sort(
        key=lambda x: int(x.get("num_users", 0)),
        reverse=True
    )

    return results


# -----------------------------
# BUILD POST
# -----------------------------

def build_post(room):

    username = room["username"]
    viewers = room.get("num_users", 0)
    age = room.get("age", "?")
    country = room.get("country") or "??"
    subject = room.get("room_subject", "")

    if len(subject) > 80:
        subject = subject[:80] + "..."

    hashtags = build_hashtags(room)

    tag_text = " ".join(f"#{t}" for t in hashtags)

    text = (
        f"🔥 {username} LIVE NOW ({viewers} watching)\n\n"
        f"{username} • {age} • {country}\n"
        f"{subject}\n\n"
        f"👉 Watch free\n\n"
        f"{tag_text}"
    )

    return text, hashtags


# -----------------------------
# POST
# -----------------------------

def post_room(client, room):

    logging.info("Downloading image")

    img = session.get(room["image_url"], timeout=15).content

    text, hashtags = build_post(room)

    facets = build_facets(
        text,
        room["chat_room_url_revshare"],
        hashtags
    )

    logging.info(f"Posting {room['username']}")

    client.send_image(
        text=text,
        image=img,
        image_alt=f"{room['username']} live cam",
        facets=facets
    )

    save_post(room["username"])


# -----------------------------
# MAIN
# -----------------------------

def main():

    init_db()

    client = Client()

    client.login(BLUESKY_HANDLE, BLUESKY_PASSWORD)

    logging.info("Logged into Bluesky")

    rooms = fetch_rooms()

    niche = random.choice(list(NICHES.keys()))

    logging.info(f"Niche: {niche}")

    filtered = filter_rooms(rooms, niche)

    if not filtered:

        logging.info("No niche matches, using fallback")

        filtered = rooms

    room = random.choice(filtered[:30])

    post_room(client, room)

    logging.info("Done")


if __name__ == "__main__":
    main()
