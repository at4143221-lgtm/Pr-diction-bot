"""
Bot Telegram Prédiction Football
"""
import os
import re
import time
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8857471496:AAFCtvt4WuTwV0zGf_jYQ9_OdjaQdjpv8SA")
API_KEY = os.getenv("API_FOOTBALL_KEY", "f604b322e3b6aa2b1cac06e8778a3e06")
API_BASE = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}
MAX_MATCHES = 12

_cache = {}
def cache_get(key, ttl=600):
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < ttl:
            return val
    return None
def cache_set(key, val):
    _cache[key] = (time.time(), val)

def api_get(endpoint, params=None):
    try:
        r = requests.get(f"{API_BASE}/{endpoint}", headers=HEADERS, params=params or {}, timeout=15)
        data = r.json()
        if data.get("errors"):
            logger.warning(f"API error: {data['errors']}")
            return None
        return data.get("response", [])
    except Exception as e:
        logger.error(f"Request error: {e}")
        return None

def get_live():
    c = cache_get("live", 45)
    if c is not None:
        return c
    data = api_get("fixtures", {"live": "all"}) or []
    cache_set("live", data)
    return data

def get_today():
    from datetime import datetime
    today = datetime.utcnow().strftime("%Y-%m-%d")
    c = cache_get(f"today:{today}", 480)
    if c is not None:
        return c
    data = api_get("fixtures", {"date": today, "timezone": "Europe/Paris"}) or []
    cache_set(f"today:{today}", data)
    return data

def get_fixture(fid):
    c = cache_get(f"fix:{fid}", 180)
    if c is not None:
        return c
    data = api_get("fixtures", {"id": fid})
    result = data[0] if data else None
    if result:
        cache_set(f"fix:{fid}", result)
    return result

def get_predictions(fid):
    c = cache_get(f"pred:{fid}", 1200)
    if c is not None:
        return c
    data = api_get("predictions", {"fixture": fid})
    result = data[0] if data else None
    if result:
        cache_set(f"pred:{fid}", result)
    return result

def get_h2h(t1, t2):
    key = f"h2h:{min(t1,t2)}-{max(t1,t2)}"
    c = cache_get(key, 43200)
    if c is not None:
        return c[:5]
    data = api_get("fixtures/headtohead", {"h2h": f"{t1}-{t2}"}) or []
    cache_set(key, data)
    return data[:5]

PRIORITY_IDS = {2, 3, 39, 140, 135, 78, 61, 94, 88, 848}

def is_priority(f):
    lid = f.get("league", {}).get("id")
    if lid in PRIORITY_IDS:
        return True
    name = (f.get("league", {}).get("name") or "").lower()
    return any(x in name for x in ["champions league", "premier league", "la liga", "serie a", "bundesliga", "ligue 1"])

def sort_fixtures(fixtures):
    live_st = {"1H", "2H", "HT", "ET", "P", "LIVE"}
    live, prio, other = [], [], []
    for f in fixtures:
        st = f.get("fixture", {}).get("status", {}).get("short", "")
        if st in live_st:
            live.append(f)
        elif is_priority(f):
            prio.append(f)
        else:
            other.append(f)
    prio.sort(key=lambda x: x.get("fixture", {}).get("date", ""))
    return live + prio + other

def safe(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d

def estimate_markets(pred):
    r = {"ht": "1-0 ou 0-0", "corners": "Over 9.5", "cards": "Over 3.5", "btts": "Oui", "ou25": "Over 2.5"}
    if not pred:
        return r
    pct = safe(pred, "predictions", "percent", default={}) or {}
    try:
        hp = int(re.sub(r"[^\d]", "", str(pct.get("home", "40"))) or 40)
        ap = int(re.sub(r"[^\d]", "", str(pct.get("away", "30"))) or 30)
        dp = int(re.sub(r"[^\d]", "", str(pct.get("draw", "30"))) or 30)
    except Exception:
        hp, ap, dp = 40, 30, 30
    if hp >= 55:
        r["ht"] = "1-0"
    elif ap >= 55:
        r["ht"] = "0-1"
    elif abs(hp - ap) <= 8:
        r["ht"] = "0-0 ou 1-1"
    else:
        r["ht"] = "1-0 ou 0-1"
    r["corners"] = "Over 10.5" if (hp >= 62 or ap >= 62) else "Over 9.5"
    r["cards"] = "Over 4.5" if (abs(hp - ap) <= 12 or dp >= 28) else "Over 3.5"
    uo = str(safe(pred, "predictions", "under_over", default="") or "")
    r["btts"] = "Oui" if ("Over" in uo or (hp > 25 and ap > 25 and abs(hp-ap) < 25)) else "Non"
    if "Under" in uo:
        r["ou25"] = "Under 2.5"
    elif "Over" in uo or hp >= 50 or ap >= 50:
        r["ou25"] = "Over 2.5"
    return r

def analyze(fixture):
    fid = fixture["fixture"]["id"]
    home = fixture["teams"]["home"]
    away = fixture["teams"]["away"]
    league = fixture["league"]["name"]
    status = fixture["fixture"]["status"]["short"]
    date = fixture["fixture"]["date"][:16].replace("T", " ")
    pred = get_predictions(fid)
    h2h = get_h2h(home["id"], away["id"])
    m = estimate_markets(pred)
    lines = [
        "🤖 **ANALYSE IA**",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🏆 {league}",
        f"📅 {date}",
        f"⚔️  **{home['name']}** vs **{away['name']}**",
        f"Statut : `{status}`",
        "",
    ]
    if status in ("1H", "2H", "HT", "ET", "P"):
        gh, ga = fixture["goals"].get("home"), fixture["goals"].get("away")
        elapsed = fixture["fixture"]["status"].get("elapsed") or "?"
        if gh is not None and ga is not None:
            lines += [f"🔴 **EN DIRECT** {elapsed}' → **{gh} - {ga}**", ""]
    if pred:
        winner = safe(pred, "predictions", "winner", "name", default="N/A")
        advice = safe(pred, "predictions", "advice", default="") or ""
        pct = safe(pred, "predictions", "percent", default={}) or {}
        gh = safe(pred, "predictions", "goals", "home", default="?")
        ga = safe(pred, "predictions", "goals", "away", default="?")
        uo = safe(pred, "predictions", "under_over", default="") or ""
        lines += [
            "📊 **Prédiction principale**",
            f"• Vainqueur : **{winner}**",
            f"• Probabilités : 🏠 {pct.get('home','?')} | ⚖️ {pct.get('draw','?')} | ✈️ {pct.get('away','?')}",
            f"• Score attendu : **{gh} - {ga}**",
        ]
        if uo:
            lines.append(f"• Over/Under : {uo}")
        if advice:
            lines.append(f"• Conseil : _{advice}_")
        lines.append("")
        comp = safe(pred, "comparison", default={}) or {}
        if comp:
            lines.append("⚖️ **Comparaison des forces**")
            for key, label in [("att","Attaque"),("def","Défense"),("form","Forme"),("h2h","H2H"),("goals","Buts")]:
                val = comp.get(key) or {}
                if val:
                    lines.append(f"• {label} : 🏠 {val.get('home','?')} vs ✈️ {val.get('away','?')}")
            lines.append("")
    else:
        lines += ["⚠️ Prédiction non disponible.", ""]
    if h2h:
        lines.append("🔄 **Confrontations directes**")
        for match in h2h[:5]:
            try:
                hn = match["teams"]["home"]["name"]
                an = match["teams"]["away"]["name"]
                sc = f"{match['goals']['home']}-{match['goals']['away']}"
                dt = match["fixture"]["date"][:10]
                lines.append(f"• {dt} : {hn} {sc} {an}")
            except Exception:
                pass
        lines.append("")
    lines += [
        "🎯 **Marchés (IA)**",
        f"• **Mi-temps** : {m['ht']}",
        f"• **BTTS** : **{m['btts']}**",
        f"• **Over/Under 2.5** : **{m['ou25']}**",
        f"• **Corners** : {m['corners']}",
        f"• **Cartons jaunes** : {m['cards']}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "_Analyse IA + API-Football • Cache activé_",
        "_Les paris comportent des risques._",
    ]
    return "\n".join(lines)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 **Bot de Prédiction Football**\n\n"
        "• /matchs → Matchs du jour (UCL en premier)\n"
        "• /ucl → Ligue des Champions\n"
        "• /live → Matchs en cours\n"
        "• /status → État\n\n"
        "Clique **🔍 Analyser** pour l'analyse IA.\n\n"
        "🔗 https://t.me/Notifia_alert_bot"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = api_get("status")
    ok = data is not None
    msg = "✅ API OK" if ok else "❌ API inaccessible"
    await update.message.reply_text(f"{msg}\nCache: {len(_cache)} entrées")

async def matchs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Chargement...")
    live, today = get_live(), get_today()
    seen, fixtures = set(), []
    for f in live + today:
        fid = f["fixture"]["id"]
        if fid not in seen:
            seen.add(fid)
            fixtures.append(f)
    if not fixtures:
        await update.message.reply_text("Aucun match trouvé.")
        return
    fixtures = sort_fixtures(fixtures)[:MAX_MATCHES]
    await update.message.reply_text(f"📋 {len(fixtures)} matchs (UCL + tops ligues prioritaires)")
    for f in fixtures:
        try:
            home, away = f["teams"]["home"]["name"], f["teams"]["away"]["name"]
            status = f["fixture"]["status"]["short"]
            league = f["league"]["name"]
            t = f["fixture"]["date"][11:16]
            score = ""
            if status in ("1H","2H","HT","ET","P","FT","AET","PEN"):
                gh, ga = f["goals"].get("home"), f["goals"].get("away")
                if gh is not None and ga is not None:
                    score = f" {gh}-{ga}"
            badge = "⭐ " if is_priority(f) else ""
            text = f"{badge}⚽ *{home}* vs *{away}*{score}\n🏟 {league} | 🕐 {t} | `{status}`"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Analyser", callback_data=f"a:{f['fixture']['id']}")]])
            await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning(f"skip: {e}")

async def live_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Matchs en direct...")
    fixtures = sort_fixtures(get_live())[:MAX_MATCHES]
    if not fixtures:
        await update.message.reply_text("Aucun match en direct.")
        return
    for f in fixtures:
        try:
            home, away = f["teams"]["home"]["name"], f["teams"]["away"]["name"]
            status = f["fixture"]["status"]["short"]
            elapsed = f["fixture"]["status"].get("elapsed") or "?"
            league = f["league"]["name"]
            gh, ga = f["goals"].get("home"), f["goals"].get("away")
            score = f"{gh}-{ga}" if gh is not None and ga is not None else "?-?"
            badge = "⭐ " if is_priority(f) else ""
            text = f"{badge}🔴 *{home}* {score} *{away}*\n🏟 {league} | {elapsed}' | `{status}`"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Analyser", callback_data=f"a:{f['fixture']['id']}")]])
            await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning(f"live skip: {e}")

async def ucl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Ligue des Champions...")
    allf = get_live() + get_today()
    fixtures, seen = [], set()
    for f in allf:
        lid = f.get("league", {}).get("id")
        name = (f.get("league", {}).get("name") or "").lower()
        if lid == 2 or ("champions league" in name and "youth" not in name and "afc" not in name):
            fid = f["fixture"]["id"]
            if fid not in seen:
                seen.add(fid)
                fixtures.append(f)
    if not fixtures:
        await update.message.reply_text("Aucun match UCL aujourd'hui.")
        return
    await update.message.reply_text(f"⭐ **Ligue des Champions** — {len(fixtures)} match(s)")
    for f in sort_fixtures(fixtures):
        try:
            home, away = f["teams"]["home"]["name"], f["teams"]["away"]["name"]
            status = f["fixture"]["status"]["short"]
            t = f["fixture"]["date"][11:16]
            score = ""
            if status in ("1H","2H","HT","ET","P","FT","AET","PEN"):
                gh, ga = f["goals"].get("home"), f["goals"].get("away")
                if gh is not None and ga is not None:
                    score = f" {gh}-{ga}"
            text = f"⭐ ⚽ *{home}* vs *{away}*{score}\n🕐 {t} | `{status}`"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Analyser", callback_data=f"a:{f['fixture']['id']}")]])
            await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning(f"ucl skip: {e}")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    data = query.data or ""
    if not data.startswith("a:"):
        return
    try:
        fid = int(data.split(":")[1])
    except Exception:
        return
    try:
        await query.edit_message_text("🤖 Analyse IA en cours...")
    except Exception:
        pass
    try:
        fixture = get_fixture(fid)
        if not fixture:
            await query.edit_message_text("❌ Match introuvable.")
            return
        report = analyze(fixture)
        if len(report) > 4000:
            report = report[:3900] + "\n\n...(tronqué)"
        try:
            await query.edit_message_text(report, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            plain = report.replace("**","").replace("*","").replace("_","").replace("`","")
            await query.edit_message_text(plain)
    except Exception as e:
        logger.exception("analyze error")
        try:
            await query.edit_message_text(f"⚠️ Erreur. Réessaie.\n({str(e)[:100]})")
        except Exception:
            pass

async def error_handler(update, context):
    logger.error("Error:", exc_info=context.error)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("matchs", matchs))
    app.add_handler(CommandHandler("live", live_cmd))
    app.add_handler(CommandHandler("ucl", ucl))
    app.add_handler(CallbackQueryHandler(button))
    app.add_error_handler(error_handler)
    print("🤖 Bot démarré")
    app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()
