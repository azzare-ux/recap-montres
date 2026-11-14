"""
Recap Montres Hebdo
--------------------
Lit une liste de flux RSS horlogerie, garde les articles de la dernière
semaine COMPLÈTE (lundi -> dimanche) qui parlent de tes marques ou mots-clés,
supprime les doublons entre sources, puis :
  1. poste le récap dans ton canal (album de photos + texte + lien du site)
  2. t'envoie en privé un BRIEF (fichier .txt) : ton prompt habituel + les
     articles de la semaine avec leurs liens, prêt à donner à ton IA
  3. t'alerte en privé si quelque chose plante

Variables d'environnement attendues :
  TELEGRAM_TOKEN   -> le token donné par @BotFather
  TELEGRAM_CHAT_ID -> @tonchannel (public) ou -100xxxxxxxxxx (privé)
  ALERT_CHAT_ID    -> ton ID personnel (alertes + brief privé)
  SEND_MODE        -> "tout" (défaut : canal + brief) ou "prive" (brief seul)
"""

import html
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

import feedparser
import requests

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Europe/Paris")
except Exception:  # base de fuseaux absente (ex : Windows sans tzdata)
    TZ = timezone.utc

# ---------------------------------------------------------------------
# 0. INTERRUPTEURS (True = activé, False = désactivé)
# ---------------------------------------------------------------------
ENABLE_DEDUP = True         # supprime les articles en double entre sources
ENABLE_TOP_PREVIEW = False  # grande image en haut du message (même message que le texte)
ENABLE_IMAGES = True        # album de photos séparé, envoyé AVANT le texte
ENABLE_ALERTS = True        # t'écrit en privé si un flux ou le script plante
ENABLE_BRIEF = True         # t'envoie en privé le brief pour ton IA (fichier .txt)
TEST_ALERT = False          # True = fait planter le script exprès pour tester l'alerte
DEBUG_FILTER = True         # écrit dans les logs pourquoi chaque article est gardé ou écarté

MAX_IMAGES = 3              # nombre de photos de l'album (si ENABLE_IMAGES)

# "calendar" = dernière semaine COMPLÈTE, du lundi au dimanche (comme ton édition).
#              Le résultat est le même quel que soit le jour où le script tourne.
# "rolling"  = les 7 derniers jours à partir de maintenant.
PERIOD_MODE = "calendar"

# Adresse de ton site, ajoutée en bas du récap ("" = pas de lien).
SITE_URL = "https://azzare-ux.github.io/cadran/"

# "tout" = canal + brief privé (défaut) / "prive" = brief privé seulement.
# Sur GitHub, ça se choisit au clic sur "Run workflow".
SEND_MODE = os.environ.get("SEND_MODE", "tout").strip().lower()

# Fichier (dans ce repo) qui contient ton prompt habituel pour l'IA.
# S'il n'existe pas, un prompt court par défaut est utilisé.
PROMPT_FILE = "prompt_edition.txt"
DEFAULT_PROMPT = (
    "Prépare l'édition de la semaine à partir des articles ci-dessous. "
    "Ouvre chaque lien et vérifie les chiffres dans la source avant de les utiliser."
)

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

# MARQUES SUIVIES.
# Format : "Nom affiché": ["variante 1", "variante 2"],   (liste vide = pas de variante)
# Pas besoin de gérer les majuscules, les accents ni les tirets :
# "Jaeger-LeCoultre" reconnaît aussi "Jaeger LeCoultre", "jaeger‑lecoultre", etc.
# Pour ajouter une marque : une nouvelle ligne.  Pour en retirer : supprime sa ligne.
BRANDS = {
    # --- Les grandes maisons ---
    "Rolex": [],
    "Omega": [],
    "Patek Philippe": ["patek"],
    "Audemars Piguet": ["audemars"],
    "Cartier": [],
    "Tudor": [],
    "Seiko": [],
    "Grand Seiko": [],
    "Jaeger-LeCoultre": ["lecoultre", "jlc"],
    "Vacheron Constantin": ["vacheron"],
    "IWC": [],
    "Breitling": [],
    "TAG Heuer": ["heuer"],
    "Panerai": [],
    # --- Autres maisons ---
    "Hublot": [],
    "Zenith": [],
    "Longines": [],
    "Tissot": [],
    "Hamilton": [],
    "Blancpain": [],
    "Chopard": [],
    "A. Lange & Söhne": ["lange sohne"],
    "Richard Mille": [],
    "F.P. Journe": ["journe"],
    "Bell & Ross": [],
    "Oris": [],
    "Nomos": [],
    "Montblanc": [],
    "Hermès": [],
    "Louis Vuitton": [],
    "Tiffany & Co.": ["tiffany"],
    "Bulgari": ["bvlgari"],
    "Piaget": [],
    "Ulysse Nardin": [],
    "Girard-Perregaux": [],
    "Minase": [],
}

# AUTRES MOTS-CLÉS (événements, sujets...). Même format que BRANDS.
# Un article qui contient un de ces mots est gardé, même sans marque.
KEYWORDS = {
    "GPHG": [],
    "Watches and Wonders": ["watches wonders"],
    "Geneva Watch Days": [],
    "Dubai Watch Week": [],
    "LVMH Watch Week": [],
}

# L'article est cherché dans son titre, son résumé ET le début de son texte
# (nombre de caractères du texte regardés ; 0 = titre et résumé seulement).
SEARCH_BODY_CHARS = 600

MAX_ARTICLES_PER_FEED = 5
DAYS_BACK = 7  # utilisé seulement si PERIOD_MODE = "rolling"
MAX_MESSAGE_LENGTH = 4000
SHOW_PREVIEW = False  # utilisé seulement si ENABLE_TOP_PREVIEW = False
USER_AGENT = "Mozilla/5.0 (compatible; CadranBot/1.0)"

SEPARATOR = "━━━━━━━━━━━━━━"
WEEKDAYS_FR = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

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


def send_to_telegram(text, preview_url=None):
    """Envoie un message texte dans le canal. Si preview_url est donné, sa grande
    image s'affiche AU-DESSUS du texte, dans le même message."""
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }

    if preview_url:
        payload["link_preview_options"] = json.dumps(
            {
                "is_disabled": False,
                "url": preview_url,
                "prefer_large_media": True,
                "show_above_text": True,
            }
        )
    else:
        payload["link_preview_options"] = json.dumps({"is_disabled": not SHOW_PREVIEW})

    telegram_call("sendMessage", payload)


def send_document(chat_id, filename, content, caption=""):
    """Envoie un fichier texte dans une conversation."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    response = requests.post(
        url,
        data={"chat_id": chat_id, "caption": caption},
        files={"document": (filename, content.encode("utf-8"), "text/plain")},
        timeout=60,
    )
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Erreur Telegram (sendDocument) : {result.get('description', result)}")


def send_alert(text):
    """Message privé d'alerte. Ne fait jamais planter le script."""
    if not ENABLE_ALERTS:
        print("[ALERTE] Désactivée (ENABLE_ALERTS = False).")
        return
    if not ALERT_CHAT_ID:
        print("[ALERTE] ALERT_CHAT_ID est vide : secret absent ou non transmis par weekly.yml.")
        return
    if not TELEGRAM_TOKEN:
        return
    try:
        safe_text = text.replace(TELEGRAM_TOKEN, "***")[:4000]
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": ALERT_CHAT_ID, "text": safe_text},
            timeout=15,
        )
        result = response.json()
        if result.get("ok"):
            print("[ALERTE] Alerte privée envoyée.")
        else:
            print(f"[ALERTE] Telegram a refusé : {result.get('description')}")
    except Exception as exc:
        print(f"[ALERTE] Échec de l'envoi : {str(exc).replace(TELEGRAM_TOKEN, '***')}")


# ---------------------------------------------------------------------
# 3. PÉRIODE (semaine lundi -> dimanche)
# ---------------------------------------------------------------------
def get_period(now=None):
    """Retourne (début, fin) : début inclus, fin exclue."""
    now = now or datetime.now(TZ)
    if PERIOD_MODE == "rolling":
        return now - timedelta(days=DAYS_BACK), now

    this_monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return this_monday - timedelta(days=7), this_monday


def _day(d):
    return "1er" if d.day == 1 else str(d.day)


def format_period(start, end):
    """Ex : 'du 19 au 25 octobre 2026'."""
    last = end - timedelta(days=1) if PERIOD_MODE == "calendar" else end
    if start.year != last.year:
        return (
            f"du {_day(start)} {MONTHS_FR[start.month - 1]} {start.year} "
            f"au {_day(last)} {MONTHS_FR[last.month - 1]} {last.year}"
        )
    if start.month != last.month:
        return (
            f"du {_day(start)} {MONTHS_FR[start.month - 1]} "
            f"au {_day(last)} {MONTHS_FR[last.month - 1]} {last.year}"
        )
    return f"du {_day(start)} au {_day(last)} {MONTHS_FR[last.month - 1]} {last.year}"


# ---------------------------------------------------------------------
# 4. MOTS-CLÉS (marques + autres)
# ---------------------------------------------------------------------
def normalize(text):
    """Met un texte sous une forme comparable : sans balises HTML, sans accents,
    en minuscules, tirets et ponctuation remplacés par des espaces."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def _compile_matchers(*groups):
    """Prépare la recherche. Les motifs les plus longs passent en premier,
    pour que 'Grand Seiko' soit reconnu avant 'Seiko'."""
    compiled = []
    for group in groups:
        for name, variants in group.items():
            for variant in [name] + list(variants):
                norm = normalize(variant)
                if norm:
                    pattern = re.compile(r"(?<![a-z0-9])" + re.escape(norm) + r"(?![a-z0-9])")
                    compiled.append((len(norm), name, pattern))
    compiled.sort(key=lambda item: -item[0])
    return [(name, pattern) for _, name, pattern in compiled]


MATCHERS = _compile_matchers(BRANDS, KEYWORDS)


def find_match(title, summary, body):
    """Retourne le mot-clé trouvé (le titre est regardé en premier),
    None si rien, ou "" si aucun filtre n'est défini."""
    if not MATCHERS:
        return ""
    for text in (title, f"{summary} {body}"):
        norm = normalize(text)
        for name, pattern in MATCHERS:
            if pattern.search(norm):
                return name
    return None


# ---------------------------------------------------------------------
# 5. NETTOYAGE ET IMAGES
# ---------------------------------------------------------------------
def clean_title(title):
    """Enlève les caractères qui peuvent casser le Markdown de Telegram."""
    title = title.replace("[", "(").replace("]", ")")
    for char in ("_", "*", "`"):
        title = title.replace(char, " ")
    return title.strip()


def format_date(dt):
    return f"{WEEKDAYS_FR[dt.weekday()]} {dt.strftime('%d/%m')}"


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

    page = ""
    if entry.get("content"):
        page = entry["content"][0].get("value", "")
    page = page or entry.get("summary", "")

    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', page)
    if match and match.group(1).startswith("http"):
        return match.group(1)

    return None


def send_images(articles_by_source):
    """Envoie un album de photos (avant le texte). Une erreur ici ne bloque jamais le récap."""
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
# 6. RÉCUPÉRATION DES ARTICLES
# ---------------------------------------------------------------------
def get_recent_entries(feed_url, start, end):
    """Retourne (articles_gardés, nombre_d_articles_dans_la_période)."""
    feed = feedparser.parse(feed_url, agent=USER_AGENT)

    if not feed.entries:
        raise RuntimeError("flux vide ou inaccessible (vérifie l'adresse)")

    kept = []
    in_window = 0

    for entry in feed.entries:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if not published:
            continue

        published_dt = datetime(*published[:6], tzinfo=timezone.utc).astimezone(TZ)
        if not (start <= published_dt < end):
            continue

        in_window += 1

        title = entry.get("title", "Sans titre")
        summary = entry.get("summary", "")

        body = ""
        if SEARCH_BODY_CHARS and entry.get("content"):
            body = normalize(entry["content"][0].get("value", ""))[:SEARCH_BODY_CHARS]

        match = find_match(title, summary, body)
        if match is None:
            if DEBUG_FILTER:
                print(f"   [FILTRE] écarté : {title[:80]}")
            continue
        if DEBUG_FILTER:
            print(f"   [FILTRE] gardé ({match or 'sans filtre'}) : {title[:80]}")

        kept.append(
            {
                "title": clean_title(title),
                "title_raw": title.strip(),
                "link": entry.get("link", ""),
                "date": published_dt,
                "match": match,
                "image": extract_image(entry),
                "also": [],
            }
        )

    kept.sort(key=lambda e: e["date"], reverse=True)
    return kept[:MAX_ARTICLES_PER_FEED], in_window


def collect_all_articles(start, end):
    """Retourne ({source: [articles]}, [sources en échec])."""
    results = {}
    failed = []
    for source_name, url in RSS_FEEDS:
        try:
            print(f"[LECTURE] {source_name}")
            entries, in_window = get_recent_entries(url, start, end)
            print(
                f"[OK] {source_name} : {in_window} article(s) dans la période, "
                f"{len(entries)} gardé(s) après filtre"
            )
            if entries:
                results[source_name] = entries
        except Exception as exc:
            print(f"[WARN] {source_name} ignoré : {exc}", file=sys.stderr)
            failed.append(f"{source_name} ({exc})")
    return results, failed


# ---------------------------------------------------------------------
# 7. DÉDOUBLONNAGE
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
# 8. FORMATAGE ET DÉCOUPAGE DU MESSAGE
# ---------------------------------------------------------------------
def site_footer():
    """Lignes optionnelles avec le lien vers ton site (vide si SITE_URL est vide)."""
    if not SITE_URL:
        return []
    return ["", f"📖 [Retrouver les éditions Cadran]({SITE_URL})"]


def format_message(articles_by_source, period_text):
    """Récap pour le canal (Markdown Telegram)."""
    lines = [f"⌚ *Récap Montres — semaine {period_text}*", ""]

    if not articles_by_source:
        lines.append("Rien de notable cette semaine sur tes marques.")
        lines.extend(site_footer())
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
            if art["match"]:
                details.append(art["match"])
            if art["also"]:
                details.append("aussi : " + ", ".join(clean_title(s) for s in art["also"]))

            lines.append(f"• [{art['title']}]({art['link']})")
            lines.append(f"   _{' · '.join(details)}_")
            lines.append("")

    lines.append(SEPARATOR)
    pluriel = "s" if total > 1 else ""
    lines.append(f"_{total} article{pluriel} cette semaine_")
    lines.extend(site_footer())

    return "\n".join(lines).strip()


def read_prompt():
    """Lit ton prompt habituel dans prompt_edition.txt (ou prend le prompt par défaut)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), PROMPT_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        if text:
            return text
    except OSError:
        pass
    return DEFAULT_PROMPT


def format_brief(articles_by_source, period_text):
    """Brief complet pour ton IA : ton prompt, puis les articles (liens visibles)."""
    lines = [
        read_prompt(),
        "",
        "=" * 40,
        f"DONNÉES DE LA SEMAINE — {period_text}",
        "(articles repérés automatiquement dans 7 flux RSS, filtrés par marques et mots-clés)",
        "",
    ]

    if not articles_by_source:
        lines.append("Aucun article sur tes marques et mots-clés cette semaine.")
        return "\n".join(lines)

    for source, articles in articles_by_source.items():
        lines.append(f"## {source}")
        for art in articles:
            tag = f" [{art['match']}]" if art["match"] else ""
            lines.append(f"- {format_date(art['date'])}{tag} {art['title_raw']}")
            lines.append(f"  {art['link']}")
            if art["also"]:
                lines.append(f"  (aussi chez : {', '.join(art['also'])})")
        lines.append("")

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
# 9. POINT D'ENTRÉE
# ---------------------------------------------------------------------
def pick_preview_url(articles_by_source):
    """Choisit le lien dont Telegram affichera la grande image en haut :
    l'article le plus récent (de préférence un qui a une image)."""
    all_articles = [
        a for arts in articles_by_source.values() for a in arts if a["link"]
    ]
    if not all_articles:
        return None
    with_image = [a for a in all_articles if a.get("image")]
    pool = with_image or all_articles
    return max(pool, key=lambda a: a["date"])["link"]


def post_to_channel(articles, period_text):
    message = format_message(articles, period_text)
    print(message)

    # Album de photos séparé : envoyé AVANT le texte (donc en haut)
    if ENABLE_IMAGES and articles:
        send_images(articles)

    # Grande image dans le même message que le texte
    preview_url = None
    if ENABLE_TOP_PREVIEW and articles:
        preview_url = pick_preview_url(articles)

    chunks = split_message(message)
    for i, chunk in enumerate(chunks, start=1):
        # l'image n'apparaît que sur le premier message si le récap est découpé
        send_to_telegram(chunk, preview_url if i == 1 else None)
        print(f"Message {i}/{len(chunks)} envoyé.")


def send_brief(articles, period_text, start):
    """Envoie en privé le brief (fichier .txt). Ne bloque jamais le reste."""
    if not ENABLE_BRIEF:
        return
    if not ALERT_CHAT_ID:
        print("[BRIEF] ALERT_CHAT_ID est vide : brief non envoyé.")
        return
    try:
        brief = format_brief(articles, period_text)
        filename = f"brief-cadran-{start:%Y-%m-%d}.txt"
        send_document(
            ALERT_CHAT_ID,
            filename,
            brief,
            caption=f"📎 Brief de la semaine {period_text} — à donner à ton IA",
        )
        print(f"[BRIEF] {filename} envoyé en privé.")
    except Exception as exc:
        print(f"[BRIEF] Échec de l'envoi : {str(exc).replace(TELEGRAM_TOKEN or '-', '***')}")


def run():
    if TEST_ALERT:
        raise RuntimeError("Test d'alerte : tout va bien, c'est voulu !")

    private_only = SEND_MODE == "prive"
    if private_only and not ALERT_CHAT_ID:
        raise RuntimeError(
            "Mode privé demandé, mais ALERT_CHAT_ID est vide "
            "(secret absent ou non transmis par weekly.yml)."
        )
    print(f"Mode d'envoi : {'PRIVÉ (brief seul)' if private_only else 'CANAL + BRIEF PRIVÉ'}")

    start, end = get_period()
    period_text = format_period(start, end)
    print(f"Période : {period_text} ({start:%d/%m/%Y %H:%M} -> {end:%d/%m/%Y %H:%M})")

    articles, failed = collect_all_articles(start, end)

    if failed:
        send_alert("⚠️ Cadran : flux en échec cette semaine :\n- " + "\n- ".join(failed))

    if not articles and len(failed) == len(RSS_FEEDS):
        raise RuntimeError("Tous les flux ont échoué, rien envoyé.")

    if ENABLE_DEDUP:
        articles = deduplicate(articles)

    # 1. Le récap dans le canal (sauf en mode "prive")
    if not private_only:
        post_to_channel(articles, period_text)

    # 2. Le brief privé pour ton IA
    send_brief(articles, period_text, start)


def main():
    try:
        run()
    except Exception as exc:
        send_alert(f"🚨 Cadran : le script a planté.\n{type(exc).__name__}: {exc}")
        raise  # le run apparaît en rouge sur GitHub


if __name__ == "__main__":
    main()
