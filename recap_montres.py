"""
Recap Montres Hebdo
--------------------
Lit une liste de flux RSS horlogerie, garde les articles des 7 derniers
jours qui parlent de tes marques, supprime les doublons entre sources,
envoie le récap sur Telegram (+ quelques photos) et t'alerte en privé
si quelque chose plante.

Variables d'environnement attendues :
  TELEGRAM_TOKEN   -> le token donné par @BotFather
  TELEGRAM_CHAT_ID -> @tonchannel (public) ou -100xxxxxxxxxx (privé)
  ALERT_CHAT_ID    -> (optionnel) ton ID personnel, pour recevoir les alertes
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import feedparser
import requests

# ---------------------------------------------------------------------
# 0. INTERRUPTEURS (True = activé, False = désactivé)
# ---------------------------------------------------------------------
ENABLE_DEDUP = True    # supprime les articles en double entre sources
ENABLE_IMAGES = True  # envoie quelques photos après le récap
ENABLE_ALERTS = True   # t'écrit en privé si un flux ou le script plante
TEST_ALERT = False     # True = fait planter le script exprès pour tester l'alerte

MAX_IMAGES = 3         # nombre maximum de photos envoyées

# ---------------------------------------------------------------------
# 1. CONFIGURATION
# ---------------------------------------------------------------------
RSS_FEEDS = [
    ("Monochrome Watches", "https://monochrome-watches.com/feed/"),
    ("Fratello Watches", "https://www.fratellowatches.com/feed/"),
    ("Hodinkee", "https://www.hodinkee.com/articles.rss"),
    ("Montres Passion", "https://www.montres-passion.fr/feed/"),
    ("A Blog To Watch", "https://www.ablogtowatch.com/feed/"),
    ("Worn & Wound", "https://wornandwound.com/feed/"),
    ("Time+Tide", "https://timeandtidewatches.com/feed/"),
]

SOURCE_EMOJIS = {
    "Monochrome Watches": "🔬",
    "Fratello Watches": "🏁",
    "Hodinkee": "📰",
    "Montres Passion": "🇫🇷",
    "A Blog To Watch": "🔎",
    "Worn & Wound": "🛠️",
    "Time+Tide": "🌊",
}
DEFAULT_EMOJI = "📰"

BRANDS = [
    "Rolex",
    "Omega",
    "Patek Philippe",
    "Audemars Piguet",
    "Cartier",
    "Tudor",
    "Seiko",
    "Grand Seiko",
    "Jaeger-LeCoultre",
    "Vacheron Constantin",
    "IWC",
    "Breitling",
    "TAG Heuer",
    "Panerai",
]

DAYS_BACK = 7
MAX_ARTICLES_PER_FEED = 5
MAX_MESSAGE_LENGTH = 4000
SHOW_PREVIEW = False
USER_AGENT = "Mozilla/5.0 (compatible; CadranBot/1.0)"

SEPARATOR = "━━━━━━━━━━━━━━"
WEEKDAYS_FR = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]

# Mots ignorés pour détecter les doublons (trop génériques)
STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "first", "look",
    "meet", "introducing", "introduces", "new", "watch", "watches", "review",
    "hands", "talks", "about", "into", "your", "what", "best",
    "les", "des", "une", "pour", "avec", "dans", "sur", "montre", "montres",
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ALERT_CHAT_ID = os.environ.get("ALERT_CHAT_ID")


# ---------------------------------------------------------------------
# 2. OUTILS TELEGRAM
# ---------------------------------------------------------------------
def telegram_call(method, payload):
    """Appelle l'API Telegram et lève une erreur claire si ça échoue."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID manquant. "
            "Vérifie tes secrets GitHub."
        )
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    response = requests.post(url, data=payload, timeout=30)
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Erreur Telegram ({method}) : {result.get('description', result)}")
    return result


def send_to_telegram(text):
    telegram_call(
        "sendMessage",
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": not SHOW_PREVIEW,
        },
    )


def send_alert(text):
    """Message privé d'alerte. Ne fait jamais planter le script."""
    if not ENABLE_ALERTS or not ALERT_CHAT_ID or not TELEGRAM_TOKEN:
        return
    try:
        safe_text = text.replace(TELEGRAM_TOKEN, "***")[:4000]
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": ALERT_CHAT_ID, "text": safe_text},
            timeout=15,
        )
    except Exception as exc:
        print(f"[WARN] Alerte non envoyée : {str(exc).replace(TELEGRAM_TOKEN, '***')}", file=sys.stderr)


# ---------------------------------------------------------------------
# 3. FILTRE PAR MARQUE ET NETTOYAGE
# ---------------------------------------------------------------------
def find_brand(title, summary):
    """Marque trouvée, None si aucune, "" si pas de filtre (BRANDS vide)."""
    if not BRANDS:
        return ""
    text = f"{title} {summary}".lower()
    for brand in BRANDS:
        if brand.lower() in text:
            return brand
    return None


def clean_title(title):
    """Enlève les caractères qui peuvent casser le Markdown de Telegram."""
    title = title.replace("[", "(").replace("]", ")")
    for char in ("_", "*", "`"):
        title = title.replace(char, " ")
    return title.strip()


def format_date(dt):
    return f"{WEEKDAYS_FR[dt.weekday()]} {dt.strftime('%d/%m')}"


# ---------------------------------------------------------------------
# 4. IMAGES
# ---------------------------------------------------------------------
def extract_image(entry):
    """Cherche une image dans l'article RSS. Retourne une URL ou None."""
    for key in ("media_content", "media_thumbnail"):
        for media in entry.get(key, []) or []:
            url = media.get("url", "")
            if url.startswith("http"):
                return url

    for enc in entry.get("enclosures", []) or []:
        if enc.get("type", "").startswith("image") and enc.get("href", "").startswith("http"):
            return enc["href"]

    html = ""
    if entry.get("content"):
        html = entry["content"][0].get("value", "")
    html = html or entry.get("summary", "")

    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html)
    if match and match.group(1).startswith("http"):
        return match.group(1)

    return None


def send_images(articles_by_source):
    """Envoie jusqu'à MAX_IMAGES photos. Une erreur ici ne bloque jamais le récap."""
    candidates = [
        art
        for articles in articles_by_source.values()
        for art in articles
        if art.get("image")
    ]
    candidates.sort(key=lambda a: a["date"], reverse=True)
    selected = candidates[:MAX_IMAGES]

    if not selected:
        print("[INFO] Aucune image trouvée dans les articles.")
        return

    def caption(art):
        return f"[{art['title']}]({art['link']})"

    try:
        if len(selected) == 1:
            art = selected[0]
            telegram_call(
                "sendPhoto",
                {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "photo": art["image"],
                    "caption": caption(art),
                    "parse_mode": "Markdown",
                },
            )
        else:
            media = [
                {
                    "type": "photo",
                    "media": art["image"],
                    "caption": caption(art),
                    "parse_mode": "Markdown",
                }
                for art in selected
            ]
            telegram_call(
                "sendMediaGroup",
                {"chat_id": TELEGRAM_CHAT_ID, "media": json.dumps(media)},
            )
        print(f"{len(selected)} image(s) envoyée(s).")
    except Exception as exc:
        # Une image refusée fait échouer tout l'album : on réessaie une par une.
        print(f"[WARN] Album refusé ({exc}), envoi image par image.", file=sys.stderr)
        for art in selected:
            try:
                telegram_call(
                    "sendPhoto",
                    {
                        "chat_id": TELEGRAM_CHAT_ID,
                        "photo": art["image"],
                        "caption": caption(art),
                        "parse_mode": "Markdown",
                    },
                )
            except Exception as exc2:
                print(f"[WARN] Image ignorée ({art['title'][:40]}) : {exc2}", file=sys.stderr)


# ---------------------------------------------------------------------
# 5. RÉCUPÉRATION DES ARTICLES
# ---------------------------------------------------------------------
def get_recent_entries(feed_url, days_back=DAYS_BACK):
    """Retourne (articles_gardés, nombre_d_articles_récents_lus)."""
    feed = feedparser.parse(feed_url, agent=USER_AGENT)

    if not feed.entries:
        raise RuntimeError("flux vide ou inaccessible (vérifie l'adresse)")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    recent = []
    in_window = 0

    for entry in feed.entries:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if not published:
            continue

        published_dt = datetime(*published[:6], tzinfo=timezone.utc)
        if published_dt < cutoff:
            continue

        in_window += 1

        title = entry.get("title", "Sans titre")
        summary = entry.get("summary", "")

        brand = find_brand(title, summary)
        if brand is None:
            continue

        recent.append(
            {
                "title": clean_title(title),
                "link": entry.get("link", ""),
                "date": published_dt,
                "brand": brand,
                "image": extract_image(entry),
                "also": [],
            }
        )

    recent.sort(key=lambda e: e["date"], reverse=True)
    return recent[:MAX_ARTICLES_PER_FEED], in_window


def collect_all_articles():
    """Retourne ({source: [articles]}, [sources en échec])."""
    results = {}
    failed = []
    for source_name, url in RSS_FEEDS:
        try:
            entries, in_window = get_recent_entries(url)
            print(
                f"[OK] {source_name} : {in_window} article(s) récent(s), "
                f"{len(entries)} gardé(s) après filtre"
            )
            if entries:
                results[source_name] = entries
        except Exception as exc:
            print(f"[WARN] {source_name} ignoré : {exc}", file=sys.stderr)
            failed.append(f"{source_name} ({exc})")
    return results, failed


# ---------------------------------------------------------------------
# 6. DÉDOUBLONNAGE
# ---------------------------------------------------------------------
def title_tokens(title):
    words = re.findall(r"[a-zà-ÿ0-9]+", title.lower())
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}


def is_duplicate(tokens_a, tokens_b):
    """Deux titres sont jugés identiques s'ils partagent au moins 3 mots
    importants et au moins 60% des mots du plus court."""
    common = tokens_a & tokens_b
    if len(common) < 3:
        return False
    return len(common) / min(len(tokens_a), len(tokens_b)) >= 0.6


def deduplicate(articles_by_source):
    """Garde la première occurrence, note les autres sources dans 'also'."""
    kept = []
    cleaned = {}

    for source, articles in articles_by_source.items():
        for art in articles:
            tokens = title_tokens(art["title"])

            original = None
            for other in kept:
                same_link = art["link"] and art["link"] == other["link"]
                if same_link or is_duplicate(tokens, other["tokens"]):
                    original = other
                    break

            if original:
                original["also"].append(source)
                print(f"[DEDUP] Doublon ignoré ({source}) : {art['title'][:60]}")
                continue

            art["tokens"] = tokens
            kept.append(art)
            cleaned.setdefault(source, []).append(art)

    return cleaned


# ---------------------------------------------------------------------
# 7. FORMATAGE ET DÉCOUPAGE DU MESSAGE
# ---------------------------------------------------------------------
def format_message(articles_by_source):
    today = datetime.now().strftime("%d/%m/%Y")
    lines = [f"⌚ *Récap Montres — semaine du {today}*", ""]

    if not articles_by_source:
        lines.append("Rien de notable cette semaine sur tes marques.")
        return "\n".join(lines)

    total = 0
    for source, articles in articles_by_source.items():
        emoji = SOURCE_EMOJIS.get(source, DEFAULT_EMOJI)
        lines.append(SEPARATOR)
        lines.append(f"{emoji} *{clean_title(source)}*")
        lines.append("")

        for art in articles:
            total += 1
            details = [format_date(art["date"])]
            if art["brand"]:
                details.append(art["brand"])
            if art["also"]:
                details.append("aussi : " + ", ".join(clean_title(s) for s in art["also"]))

            lines.append(f"• [{art['title']}]({art['link']})")
            lines.append(f"   _{' · '.join(details)}_")
            lines.append("")

    lines.append(SEPARATOR)
    pluriel = "s" if total > 1 else ""
    lines.append(f"_{total} article{pluriel} cette semaine_")

    return "\n".join(lines).strip()


def split_message(text, max_length=MAX_MESSAGE_LENGTH):
    """Découpe le texte en morceaux <= max_length, en coupant entre deux lignes."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    current = ""

    for line in text.split("\n"):
        while len(line) > max_length:
            if current:
                chunks.append(current.rstrip())
                current = ""
            chunks.append(line[:max_length])
            line = line[max_length:]

        if len(current) + len(line) + 1 > max_length:
            chunks.append(current.rstrip())
            current = ""

        current += line + "\n"

    if current.strip():
        chunks.append(current.rstrip())

    return chunks


# ---------------------------------------------------------------------
# 8. POINT D'ENTRÉE
# ---------------------------------------------------------------------
def run():
    if TEST_ALERT:
        raise RuntimeError("Test d'alerte : tout va bien, c'est voulu !")

    articles, failed = collect_all_articles()

    if failed:
        send_alert("⚠️ Cadran : flux en échec cette semaine :\n- " + "\n- ".join(failed))

    if not articles and len(failed) == len(RSS_FEEDS):
        raise RuntimeError("Tous les flux ont échoué, rien envoyé aux abonnés.")

    if ENABLE_DEDUP:
        articles = deduplicate(articles)

    message = format_message(articles)
    print(message)

    chunks = split_message(message)
    for i, chunk in enumerate(chunks, start=1):
        send_to_telegram(chunk)
        print(f"Message {i}/{len(chunks)} envoyé.")

    if ENABLE_IMAGES and articles:
        send_images(articles)


def main():
    try:
        run()
    except Exception as exc:
        send_alert(f"🚨 Cadran : le script a planté.\n{type(exc).__name__}: {exc}")
        raise  # le run apparaît en rouge sur GitHub


if __name__ == "__main__":
    main()
