import json
import re
import os
import time
import uuid
import random
import calendar
import traceback
import datetime as dt
from collections.abc import Mapping

import requests
import pandas as pd
import altair as alt
import streamlit as st

APP_VERSION = "7.0"

# ========================= Настройки интерфейса =========================

st.set_page_config(page_title="Путь к миллиону", page_icon="💰")
st.html(
    "<style>.block-container{padding:.7rem .8rem 3rem;max-width:780px}"
    "h1,h2,h3{margin:0;padding:.25rem 0}"
    "[data-testid=stMetricValue]{font-size:1.25rem}[data-testid=stMetricLabel]{font-size:.8rem}"
    "[data-testid=stHeader]{height:1.8rem}div[data-testid=stVerticalBlock]{gap:.55rem}"
    ".stButton button{border-radius:14px}</style>"
)

GREEN, RED, BLUE = "#10b981", "#ef4444", "#3b82f6"

G0 = {
    "Обязательные": [
        "Ипотека", "Кварплата", "Связь", "Страховка",
        "Родителям долг за ремонт и квартиру", "Учеба в вузе",
    ],
    "Еда": ["Продукты", "Обед на работе", "Кафе", "Кофе", "Алкоголь"],
    "Транспорт": ["Проезд на работу", "Транспорт", "Такси"],
    "Здоровье и уход": ["Здоровье", "Гигиена", "Стрижка"],
    "Семья": ["Важное для любимой", "Подарки"],
    "Досуг и покупки": [
        "Развлечения", "Досуг", "Отпуск", "Подписка",
        "Одежда", "Гаджеты и техника",
    ],
    "Прочее": ["Дом", "Другое", "Образование"],
}
MN = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]

ICONS = [
    "🛒", "🍽️", "🍕", "☕", "🍺", "🥦", "🚌", "🚇", "🚕", "🚗", "⛽", "🏠", "💡", "📱", "🛡️", "🎓",
    "📚", "💊", "🧴", "💇", "👗", "🎁", "❤️", "🎬", "🎮", "✈️", "🏖️", "📺", "💻", "🔧", "🐶", "👶",
    "💰", "🏦", "📦", "🧾", "🏋️", "🧹", "🤝", "🏷️",
]
COLORS = {
    "Зелёный": "#10b981", "Синий": "#3b82f6", "Красный": "#ef4444", "Оранжевый": "#f97316",
    "Жёлтый": "#eab308", "Фиолетовый": "#8b5cf6", "Розовый": "#ec4899", "Бирюзовый": "#14b8a6",
    "Серый": "#6b7280", "Коричневый": "#92400e",
}
DEFAULT_ICON = {
    "Продукты": "🛒", "Обед на работе": "🍽️", "Кафе": "🍕", "Кофе": "☕", "Алкоголь": "🍺",
    "Проезд на работу": "🚌", "Транспорт": "🚇", "Такси": "🚕", "Ипотека": "🏠", "Кварплата": "💡",
    "Связь": "📱", "Страховка": "🛡️", "Учеба в вузе": "🎓", "Здоровье": "💊", "Гигиена": "🧴",
    "Стрижка": "💇", "Одежда": "👗", "Подарки": "🎁", "Важное для любимой": "❤️", "Развлечения": "🎬",
    "Досуг": "🎮", "Отпуск": "✈️", "Подписка": "📺", "Гаджеты и техника": "💻", "Дом": "🔧",
    "Другое": "🏷️", "Образование": "📚", "Родителям долг за ремонт и квартиру": "🤝",
}
GROUP_COLOR = {
    "Обязательные": "Серый", "Еда": "Оранжевый", "Транспорт": "Синий", "Здоровье и уход": "Бирюзовый",
    "Семья": "Розовый", "Досуг и покупки": "Фиолетовый", "Прочее": "Зелёный",
}


def sec(key):
    try:
        return st.secrets[key]
    except Exception:
        return None


def money(value):
    try:
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "0 ₽"


def month_label(month):
    try:
        return f"{MN[int(month[5:7]) - 1]} {month[2:4]}"
    except Exception:
        return str(month)


def month_before(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def month_range(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield f"{y}-{m:02d}"
        m += 1
        if m > 12:
            y, m = y + 1, 1


# ========================= Авторизация =========================

password = sec("password")
if password and not st.session_state.get("ok"):
    with st.form("login"):
        entered = st.text_input("Пароль", type="password", key="login_password")
        if st.form_submit_button("Войти", type="primary"):
            if entered.strip() == str(password).strip():
                st.session_state.ok = True
                st.rerun()
            else:
                st.error("Неверный пароль")
    st.stop()


# ========================= Хранилище: Яндекс.Диск или LOCAL_DEV =========================

LOCAL = os.environ.get("LOCAL_DEV")
YANDEX_API = "https://cloud-api.yandex.net/v1/disk"


def yandex_token():
    token = sec("yandex_token")
    if token:
        return token
    try:  # токен мог случайно оказаться внутри какого-то блока [...] в Secrets
        for key in st.secrets.keys():
            sub = st.secrets[key]
            if isinstance(sub, Mapping) and sub.get("yandex_token"):
                return sub.get("yandex_token")
    except Exception:
        pass
    return None


def yandex_headers():
    token = yandex_token()
    if not token:
        raise RuntimeError("Не задан yandex_token в Secrets")
    return {"Authorization": "OAuth " + str(token)}


def local_path(path):
    full = os.path.join(LOCAL, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    return full


RETRY_STATUSES = (429, 500, 502, 503, 504)
RETRY_DELAYS = (1, 2, 4)      # паузы между повторами при временных сбоях Яндекс.Диска, сек.


def ycall(method, url, **kwargs):
    """Запрос к Яндекс.Диску с повторами при временных сбоях (503, 429, обрыв связи)."""
    response, last_error = None, None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            response = getattr(requests, method)(url, **kwargs)
            if response.status_code not in RETRY_STATUSES:
                return response
        except (requests.ConnectionError, requests.Timeout) as error:
            last_error, response = error, None
        if attempt < len(RETRY_DELAYS):
            time.sleep(RETRY_DELAYS[attempt])
    if response is not None:
        return response
    raise last_error


def sget(path):
    if LOCAL:
        full = os.path.join(LOCAL, path)
        if not os.path.exists(full):
            return None
        with open(full, "r", encoding="utf-8") as file:
            return json.load(file)

    response = ycall(
        "get", YANDEX_API + "/resources/download",
        params={"path": "app:/" + path}, headers=yandex_headers(), timeout=20,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()

    download = ycall("get", response.json()["href"], timeout=30)
    download.raise_for_status()
    return download.json()


def sput(path, value):
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")

    if LOCAL:
        with open(local_path(path), "wb") as file:
            file.write(payload)
        return

    folder = path.split("/")[0] if "/" in path else None
    ready = st.session_state.setdefault("yandex_dirs", set())
    if folder and folder not in ready:
        mkdir = ycall(
            "put", YANDEX_API + "/resources",
            params={"path": "app:/" + folder}, headers=yandex_headers(), timeout=20,
        )
        if mkdir.status_code not in (201, 202, 409):
            mkdir.raise_for_status()
        ready.add(folder)

    # Ссылка для загрузки одноразовая: при сбое запрашиваем новую и повторяем всю пару запросов.
    last_error = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            response = requests.get(
                YANDEX_API + "/resources/upload",
                params={"path": "app:/" + path, "overwrite": "true"},
                headers=yandex_headers(), timeout=20,
            )
            response.raise_for_status()
            upload = requests.put(response.json()["href"], data=payload, timeout=60)
            upload.raise_for_status()
            return
        except Exception as error:
            last_error = error
            status = getattr(getattr(error, "response", None), "status_code", None)
            if status is not None and status not in RETRY_STATUSES:
                raise                       # например, 401/403 — повторять бессмысленно
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
    raise last_error


def slist(folder="backups"):
    if LOCAL:
        full = os.path.join(LOCAL, folder)
        if not os.path.isdir(full):
            return []
        return sorted([name for name in os.listdir(full) if name.endswith(".json")], reverse=True)

    response = ycall(
        "get", YANDEX_API + "/resources",
        params={"path": "app:/" + folder, "limit": 1000, "sort": "-name"},
        headers=yandex_headers(), timeout=20,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return [
        item["name"]
        for item in response.json().get("_embedded", {}).get("items", [])
        if item.get("type") == "file" and item.get("name", "").endswith(".json")
    ]


# ========================= Логи (папка logs на Яндекс.Диске) =========================

def log(event, **info):
    """Копит события сессии. Пароли и токены в логи не попадают."""
    entry = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "e": event, **info}
    events = st.session_state.setdefault("log_all", [])
    events.append(entry)
    del events[:-2000]
    st.session_state["log_dirty"] = True


def flush_logs():
    """Пишет лог сессии в logs/<дата>_<id>.json. Сбой логов никогда не ломает приложение."""
    if not st.session_state.get("log_dirty"):
        return True
    try:
        sid = st.session_state.setdefault("sid", uuid.uuid4().hex[:8])
        started = st.session_state.setdefault("sid_date", str(dt.date.today()))
        sput(
            f"logs/{started}_{sid}.json",
            {"app": APP_VERSION, "sid": sid, "date": started, "events": st.session_state.get("log_all", [])},
        )
        st.session_state["log_dirty"] = False
        return True
    except Exception:
        return False


def uid():
    """Уникальный id: время в мс × 1000 + счётчик (раньше при пакетной загрузке id совпадали)."""
    now = int(time.time() * 1000) * 1000 + random.randint(0, 99)
    value = max(now, st.session_state.get("last_uid", 0) + 1)
    st.session_state["last_uid"] = value
    return value


def fix_ids(entries):
    """Убирает дубли и пустые id (в старых данных после импорта они могли повторяться)."""
    seen, top = set(), 0
    for entry in entries:
        try:
            top = max(top, int(entry.get("id")))
        except (TypeError, ValueError):
            pass
    for entry in entries:
        try:
            value = int(entry.get("id"))
        except (TypeError, ValueError):
            value = None
        if value is None or value in seen:
            top += 1
            value = top
        entry["id"] = value
        seen.add(value)


def default_data():
    return {
        "v": 2, "rev": 0, "cfg": {},
        "cats": {category: group for group, categories in G0.items() for category in categories},
        "bud": {}, "rec": [], "exp": [], "sav": [], "inc": {}, "trash": [], "style": {},
    }


def migrate(data):
    """Дополняет старые версии структуры и исправляет безопасные значения."""
    if not isinstance(data, dict):
        data = default_data()

    result = dict(data)
    result.setdefault("cfg", {})
    cfg_local = result["cfg"] if isinstance(result["cfg"], dict) else {}
    result["cfg"] = cfg_local

    today_date = dt.date.today()
    cfg_local.setdefault("goal", 1_000_000)
    cfg_local.setdefault("income", 149_600)
    cfg_local.setdefault("cap", 90_000)
    cfg_local.setdefault("pct", cfg_local.get("rate", 25))
    cfg_local.setdefault("srate", 0.0)
    cfg_local.setdefault("frm", str(today_date))
    cfg_local.setdefault("start", 0.0)
    cfg_local.setdefault("sdate", cfg_local["frm"])

    defaults = {
        "cats": {category: group for group, categories in G0.items() for category in categories},
        "bud": {}, "rec": [], "exp": [], "sav": [], "inc": {}, "trash": [], "style": {}, "rev": 0,
    }
    for key, value in defaults.items():
        result.setdefault(key, value)

    for entry in result["exp"]:
        entry.setdefault("t", "e")
        entry.setdefault("n", "")
    for entry in result["sav"]:
        entry.setdefault("n", "")
    fix_ids(result["exp"])
    fix_ids(result["sav"])

    result["v"] = 2
    return result


def merge(local_data, remote_data):
    """Объединяет записи двух устройств. Свои (локальные) записи не теряются никогда."""
    local_data = migrate(local_data)
    remote_data = migrate(remote_data)
    out = dict(local_data)

    deleted = {
        str(item.get("id"))
        for item in local_data["trash"] + remote_data["trash"]
        if isinstance(item, dict) and "id" in item
    }

    for key in ("exp", "sav"):
        combined = {str(entry.get("id")): entry for entry in local_data[key]}
        for entry in remote_data[key]:
            entry_id = str(entry.get("id"))
            if entry_id not in combined and entry_id not in deleted:
                combined[entry_id] = entry
        out[key] = sorted(
            combined.values(),
            key=lambda entry: (str(entry.get("d", "")), int(entry.get("id", 0))),
        )

    trash_by_id = {}
    for item in remote_data["trash"] + local_data["trash"]:
        if isinstance(item, dict) and "id" in item:
            trash_by_id[str(item["id"])] = item
    out["trash"] = list(trash_by_id.values())[-500:]

    out["inc"] = {**remote_data["inc"], **local_data["inc"]}
    out["cats"] = {**remote_data["cats"], **local_data["cats"]}
    out["bud"] = {**remote_data["bud"], **local_data["bud"]}
    out["style"] = {**remote_data["style"], **local_data["style"]}
    out["rec"] = local_data["rec"]
    out["cfg"] = {**remote_data["cfg"], **local_data["cfg"]}
    out["rev"] = max(local_data.get("rev", 0), remote_data.get("rev", 0))
    return out


# ========================= Первичная загрузка =========================

if "D" not in st.session_state:
    load_started = time.time()
    st.session_state["sid"] = uuid.uuid4().hex[:8]
    st.session_state["sid_date"] = str(dt.date.today())
    log("session_start", app=APP_VERSION, streamlit=st.__version__, storage="local" if LOCAL else "yandex")

    if not (LOCAL or yandex_token()):
        try:
            found_keys = ", ".join(st.secrets.keys())
        except Exception:
            found_keys = "секретов нет"
        st.error(
            "Не задан доступ к Яндекс.Диску: в Secrets нет `yandex_token`. "
            "Он должен стоять в самом верху, ДО любой строки вида `[...]`. "
            f"Сейчас видны ключи: {found_keys or '—'}"
        )
        st.stop()

    try:
        loaded = sget("data.json")
        if loaded is None:
            backup_names = slist()
            if backup_names:
                loaded = sget("backups/" + backup_names[0])
                st.session_state.note = "Основной файл не найден — загружена последняя резервная копия."
                log("load_from_backup", name=backup_names[0])
    except Exception as error:
        log("load_fail", error=str(error)[:300])
        flush_logs()
        st.error(f"Не удалось прочитать хранилище: {error}. Данные не изменены.")
        if st.button("Повторить загрузку", key="retry_load"):
            st.rerun()
        st.stop()

    st.session_state.D = migrate(loaded if loaded else default_data())
    st.session_state.base = (loaded or {}).get("rev", 0)
    log("load_ok", ms=int((time.time() - load_started) * 1000), exp=len(st.session_state.D["exp"]),
        sav=len(st.session_state.D["sav"]), rev=st.session_state.base)


D = st.session_state.D
cfg = D["cfg"]

if st.session_state.get("note"):
    st.warning(st.session_state.pop("note"))


def save():
    """Сохраняет данные, делает резервную копию предыдущей версии и пишет лог."""
    started = time.time()
    try:
        remote = sget("data.json")
        current = st.session_state.D

        if remote and remote.get("rev", 0) != st.session_state.get("base", 0):
            current = merge(current, remote)
            st.session_state.D = current
            log("merge_conflict", remote_rev=remote.get("rev"), base=st.session_state.get("base"))
            st.info("Данные изменились на другом устройстве — записи объединены.")

        if remote:
            backup_name = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".json"
            sput("backups/" + backup_name, remote)

        current["rev"] = (remote or {}).get("rev", 0) + 1
        sput("data.json", current)
        st.session_state.base = current["rev"]
        st.session_state["unsaved"] = False
        log("save_ok", ms=int((time.time() - started) * 1000), rev=current["rev"], exp=len(current["exp"]), sav=len(current["sav"]))
        flush_logs()
        return True

    except Exception as error:
        st.session_state["unsaved"] = True
        log("save_fail", error=str(error)[:300])
        flush_logs()
        st.error(
            f"НЕ СОХРАНЕНО: {str(error)[:200]}. Приложение уже пробовало несколько раз. "
            "Изменения остались в приложении: не закрывай страницу и нажми «Повторить сохранение» "
            "(кнопка появится вверху после обновления экрана) или внеси любое другое изменение."
        )
        return False


def commit():
    if save():
        st.rerun()
    st.stop()


def add(kind, via="manual", **values):
    D[kind].append({"id": uid(), **values})
    D[kind].sort(key=lambda item: (str(item.get("d", "")), int(item.get("id", 0))))
    try:
        days_back = (dt.date.today() - dt.date.fromisoformat(str(values.get("d")))).days
    except ValueError:
        days_back = None
    log("entry_add", kind=kind, type=values.get("t") or values.get("k"), cat=values.get("c"),
        amount=values.get("a"), via=via, comment=bool(values.get("n")), days_back=days_back)


def trash(kind, entry):
    if entry in D[kind]:
        D[kind].remove(entry)
        D["trash"].append({
            "id": entry["id"], "k": kind, "e": entry,
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
        })
        D["trash"] = D["trash"][-500:]
        log("entry_delete", kind=kind, cat=entry.get("c"), amount=entry.get("a"))


# ========================= Подготовка данных и расчёты =========================

today = dt.date.today()
one_day = dt.timedelta(days=1)
current_month = today.strftime("%Y-%m")


def safe_date(value, fallback):
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return fallback


def safe_float(value, fallback=0.0):
    try:
        number = float(value)
        return number if pd.notna(number) else fallback
    except (TypeError, ValueError):
        return fallback


cfg["goal"] = max(1.0, safe_float(cfg.get("goal"), 1_000_000))
cfg["income"] = max(0.0, safe_float(cfg.get("income"), 149_600))
cfg["cap"] = max(0.0, safe_float(cfg.get("cap"), 90_000))
cfg["pct"] = min(100.0, max(0.0, safe_float(cfg.get("pct"), 25)))
cfg["srate"] = max(0.0, safe_float(cfg.get("srate"), 0))
cfg["start"] = max(0.0, safe_float(cfg.get("start"), 0))

start_month_date = min(safe_date(cfg.get("frm"), today), today)
cfg["frm"] = str(start_month_date)
cfg["sdate"] = str(safe_date(cfg.get("sdate"), start_month_date))


def apply_recurring_payments():
    """Добавляет регулярные платежи в расходы в их день месяца (после наступления дня)."""
    changed = False

    for recurring in D["rec"]:
        try:
            last_text = recurring.get("last")
            if not isinstance(last_text, str) or not re.fullmatch(r"\d{4}-\d{2}", last_text):
                year, month = month_before(today.year, today.month)
            else:
                year, month = map(int, last_text.split("-"))

            day_number = min(31, max(1, int(recurring["day"])))
            amount = float(recurring["a"])
            if amount <= 0:
                continue

            while (year, month) < (today.year, today.month):
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)
                payment_date = dt.date(year, month, min(day_number, calendar.monthrange(year, month)[1]))
                if payment_date > today:
                    break

                note = ("авто " + str(recurring.get("n", ""))).strip()
                duplicate = any(
                    entry.get("t", "e") == "e" and entry.get("n", "") == note
                    and entry.get("c") == recurring["c"] and entry.get("d") == str(payment_date)
                    and abs(safe_float(entry.get("a")) - amount) < 0.001
                    for entry in D["exp"]
                )
                if not duplicate:
                    add("exp", via="recurring", d=str(payment_date), c=recurring["c"], a=amount, n=note, t="e")

                recurring["last"] = f"{year}-{month:02d}"
                changed = True

        except (KeyError, TypeError, ValueError):
            continue

    if changed:
        commit()


apply_recurring_payments()


def make_frame(rows, columns):
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        frame["d"] = pd.Series(dtype="object")
        frame["a"] = pd.Series(dtype="float64")
        frame["m"] = pd.Series(dtype="object")
        return frame

    frame["d"] = pd.to_datetime(frame["d"], errors="coerce").dt.date
    frame["a"] = pd.to_numeric(frame["a"], errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["d"]).copy()
    frame["m"] = pd.to_datetime(frame["d"]).dt.strftime("%Y-%m")
    return frame


F = make_frame(D["exp"], ["id", "d", "c", "a", "n", "t"])
F["t"] = F["t"].fillna("e")
F["n"] = F["n"].fillna("")
F["g"] = F["c"].map(D["cats"]).fillna("Прочее")

S = make_frame(D["sav"], ["id", "d", "a", "k", "n"])
S["n"] = S["n"].fillna("")

E = F[F["t"] == "e"].copy()
C = F[F["t"] == "cb"].copy()
I = F[F["t"] == "in"].copy()

# Обязательные (регулярные) траты: платятся раз в месяц крупной суммой, поэтому в прогнозы и темпы их не «размножаем».
regular_categories = {str(item.get("c")) for item in D["rec"] if isinstance(item, dict)}
if E.empty:
    E["reg"] = pd.Series(dtype=bool)
else:
    E["reg"] = E["c"].isin(regular_categories) | (E["g"] == "Обязательные") | E["n"].astype(str).str.startswith("авто")
EV = E[~E["reg"]].copy()          # обычные (переменные) траты


def sum_between(frame, start, end):
    if frame.empty:
        return 0.0
    return float(frame.loc[(frame["d"] >= start) & (frame["d"] <= end), "a"].sum())


monthly = {}
carry = 0.0
for month in month_range(start_month_date, today):
    base_income = safe_float(D["inc"].get(month, cfg["income"]), cfg["income"])
    extra_income = float(I.loc[I["m"] == month, "a"].sum())
    income_total = base_income + extra_income
    planned_saving = income_total * cfg["pct"] / 100.0

    expenses = float(E.loc[E["m"] == month, "a"].sum())
    saved_percent = float(S.loc[(S["m"] == month) & (S["k"] == "p25"), "a"].sum())
    other_saving = float(S.loc[(S["m"] == month) & S["k"].isin(["dep", "rest"]), "a"].sum())
    withdrawals = float(S.loc[(S["m"] == month) & (S["k"] == "wd"), "a"].sum())

    cash = carry + income_total - expenses - saved_percent - other_saving + withdrawals
    amount_to_save = max(0.0, planned_saving - saved_percent)

    monthly[month] = {
        "base": base_income, "ex": extra_income, "inc": income_total, "pl": planned_saving,
        "sp": expenses, "p25": saved_percent, "need": amount_to_save,
        "rest": cash - amount_to_save, "cin": carry,
    }
    carry = cash

mc = monthly.get(current_month, {
    "base": cfg["income"], "ex": 0.0, "inc": cfg["income"],
    "pl": cfg["income"] * cfg["pct"] / 100, "sp": 0.0,
    "p25": 0.0, "need": cfg["income"] * cfg["pct"] / 100,
    "rest": 0.0, "cin": 0.0,
})


def pending_mandatory():
    """Обязательные (регулярные) платежи этого месяца, которые ещё не списаны."""
    items = []
    for recurring in D["rec"]:
        try:
            if str(recurring.get("last")) != current_month and float(recurring["a"]) > 0:
                items.append(recurring)
        except (KeyError, TypeError, ValueError):
            continue
    return items


pending = pending_mandatory()
reserve = sum(safe_float(item.get("a")) for item in pending)
rest_net = mc["rest"] - reserve     # реальный остаток: уже вычтены обязательные платежи месяца


def savings_engine(until):
    flows = [(safe_date(cfg["sdate"], today), cfg["start"])]
    flows += [(row.d, -float(row.a) if row.k == "wd" else float(row.a)) for row in S.itertuples()]
    flows += [(row.d, float(row.a)) for row in C.itertuples()]
    flows = sorted((date, amount) for date, amount in flows if date <= until)

    if not flows:
        return 0.0, 0.0

    rate_per_day = cfg["srate"] / 100.0 / 365.0
    balance_value = principal_value = 0.0
    index = 0
    date = flows[0][0]

    while date <= until:
        balance_value *= 1.0 + rate_per_day
        while index < len(flows) and flows[index][0] == date:
            balance_value += flows[index][1]
            principal_value += flows[index][1]
            index += 1
        date += one_day

    return balance_value, principal_value


balance, principal = savings_engine(today)
interest = balance - principal
daily_rate = cfg["srate"] / 100.0 / 365.0
year_interest = balance * ((1.0 + daily_rate) ** 365 - 1.0)

first_expense = F["d"].min() if not F.empty else today
window_days = min(30, max(1, (today - first_expense).days + 1))
window_start = today - dt.timedelta(days=window_days - 1)
variable_daily = sum_between(EV, window_start, today) / window_days          # обычные траты в день
history_months = min(3.0, max(1.0, (today - first_expense).days / 30.4))
regular_other = float(E.loc[
    E["reg"] & (E["d"] >= today - dt.timedelta(days=90)) & ~E["c"].isin(regular_categories), "a"
].sum()) / history_months
regular_monthly = sum(safe_float(item.get("a")) for item in D["rec"]) + regular_other   # обязательные: раз в месяц
cashback_monthly = sum_between(C, window_start, today) / window_days * 30.4
monthly_expenses_est = variable_daily * 30.4 + regular_monthly
monthly_addition = max(mc["inc"] - monthly_expenses_est, 0.0) + cashback_monthly

days_in_current = calendar.monthrange(today.year, today.month)[1]
regular_spent_month = float(E.loc[(E["m"] == current_month) & E["reg"], "a"].sum())
variable_limit_month = max(cfg["cap"] - regular_spent_month - reserve, 0.0)   # лимит на обычные траты месяца
daily_limit = variable_limit_month / days_in_current if cfg["cap"] else 0.0

projected_balance = balance
months_to_goal = 0
while (
    projected_balance < cfg["goal"]
    and months_to_goal < 240
    and (monthly_addition > 0 or daily_rate > 0)
):
    projected_balance = projected_balance * ((1.0 + daily_rate) ** 30.4) + monthly_addition
    months_to_goal += 1


# Прогноз на год вперёд: ежемесячно добавляем свободные деньги, на всё начисляются проценты.
year_balance, year_contributions = balance, 0.0
for _ in range(12):
    year_balance = year_balance * ((1.0 + daily_rate) ** 30.4) + monthly_addition
    year_contributions += monthly_addition
year_interest_total = year_balance - balance - year_contributions       # проценты за год с учётом будущих взносов


def set_amount(value):
    st.session_state["add_amount"] = value


def add_to_amount(step_value):
    st.session_state["add_amount"] = float(st.session_state.get("add_amount") or 0) + step_value


def typical_amounts(category, limit=4):
    """Самые частые суммы трат этой категории (для подстановки одним нажатием)."""
    rows = E[E["c"] == category]
    if rows.empty:
        return []
    recent = rows[rows["d"] >= today - dt.timedelta(days=180)]
    source = recent if len(recent) >= 3 else rows
    stats = source.assign(r=source["a"].round(2)).groupby("r").agg(n=("a", "size"), last=("d", "max")).sort_values(["n", "last"], ascending=False)
    return [float(value) for value in stats.index[:limit]]


def motivation_messages():
    messages = []
    today_spend = sum_between(EV, today, today)
    if today_spend > daily_limit:
        messages.append(("warning", f"Сегодня потрачено на {money(today_spend - daily_limit)} больше дневного ориентира."))
    elif today_spend > 0:
        messages.append(("info", f"Сегодня в рамках дневного ориентира. Запас {money(daily_limit - today_spend)}."))
    else:
        messages.append(("info", "Пока нет трат за сегодня. Не забудь внести расходы вечером."))

    week_start = today - dt.timedelta(days=today.weekday())
    previous_week_start = week_start - dt.timedelta(days=7)
    elapsed = (today - week_start).days
    current_week = sum_between(EV, week_start, today)
    previous_week = sum_between(EV, previous_week_start, previous_week_start + dt.timedelta(days=elapsed))

    if sum_between(EV, previous_week_start, week_start - one_day) > 0:
        difference = current_week - previous_week
        if difference > 0:
            messages.append(("warning", f"За неделю обычных трат (без обязательных) на {money(difference)} больше, чем за такой же период прошлой недели."))
        else:
            messages.append(("info", f"За неделю обычных трат на {money(-difference)} меньше. Хорошая динамика!"))

    current_categories = EV.loc[EV["d"] >= week_start].groupby("c")["a"].sum()
    previous_categories = EV.loc[
        (EV["d"] >= previous_week_start) & (EV["d"] <= previous_week_start + dt.timedelta(days=elapsed))
    ].groupby("c")["a"].sum()
    difference_by_category = current_categories.sub(previous_categories, fill_value=0)

    if not difference_by_category.empty and difference_by_category.max() > 500:
        messages.append(("warning", f"Сильнее всего выросла категория «{difference_by_category.idxmax()}»: +{money(difference_by_category.max())}."))

    return messages


# ========================= Иконки и цвета категорий =========================

def style_of(category):
    """(иконка, цвет в hex, название цвета) категории."""
    custom = D["style"].get(category, {}) if isinstance(D.get("style"), dict) else {}
    group = D["cats"].get(category, "Прочее")
    icon = custom.get("i") or DEFAULT_ICON.get(category) or "🏷️"
    color_name = custom.get("c") if custom.get("c") in COLORS else None
    color_name = color_name or GROUP_COLOR.get(group) or list(COLORS)[sum(map(ord, group)) % len(COLORS)]
    return icon, COLORS[color_name], color_name


def tile_css(items, selected=None):
    """CSS для плиток-кнопок: items = [(key, category)]. Выбранная плитка — залитая цветом."""
    rules = []
    for key, category in items:
        _, color, _ = style_of(category)
        if category == selected:
            rules.append(f".st-key-{key} button{{background:{color}!important;color:#fff!important;border:2px solid {color}!important;border-radius:14px!important}}")
        else:
            rules.append(f".st-key-{key} button{{background:{color}22!important;border:1px solid {color}!important;border-radius:14px!important}}")
    return "<style>" + "".join(rules) + "</style>" if rules else ""


def quick_expenses(limit=6):
    """Разные (по категориям) самые частые траты с их типичной суммой."""
    recent = E[E["d"] >= today - dt.timedelta(days=90)]
    source = recent if len(recent) >= 5 else E
    rows = []
    for category, group in source.groupby("c"):
        if category not in D["cats"]:
            continue
        rounded = group.assign(r=group["a"].round(2))
        stats = rounded.groupby("r").agg(n=("a", "size"), last=("d", "max")).sort_values(["n", "last"], ascending=False)
        rows.append((len(group), group["d"].max(), category, float(stats.index[0])))
    rows.sort(reverse=True)
    return [(category, amount) for _, _, category, amount in rows[:limit]]


def run_ui():
    # ========================= Интерфейс =========================

    P_HOME, P_ADD, P_AN, P_SAV = "🏠 Главная", "➕ Внести", "📊 Аналитика", "💰 Накопления"
    P_HIS, P_GRP, P_MORE = "📜 История", "🗂 Группы", "⚙️ Ещё"
    PAGES = [P_HOME, P_ADD, P_AN, P_SAV, P_HIS, P_GRP, P_MORE]

    st.markdown("### 💰 Путь к миллиону")
    page = st.pills("Раздел", PAGES, default=P_HOME, required=True, key="nav", label_visibility="collapsed")
    page = page or P_HOME
    if st.session_state.get("prev_page") != page:
        log("nav", page=page)
        st.session_state["prev_page"] = page

    if st.session_state.get("unsaved"):
        st.warning("⚠️ Последние изменения ещё не сохранены на Яндекс.Диск. Они остаются в приложении — не закрывай страницу.")
        if st.button("Повторить сохранение", key="retry_save", type="primary"):
            commit()

    cat_ids = {category: index for index, category in enumerate(sorted(D["cats"]))}


    # ========================= Главная =========================

    if page == P_HOME:
        st.metric(
            "Накоплено (реально отложено)",
            money(balance),
            f"{balance / cfg['goal'] * 100:.1f}% от {money(cfg['goal'])}",
            delta_color="off",
        )
        st.progress(max(0.0, min(1.0, balance / cfg["goal"])))

        caption = (
            f"Вложено {money(principal)} · проценты {money(interest)} · "
            f"ставка {cfg['srate']:g}% · ещё примерно {money(year_interest)} за год"
        )
        if balance >= cfg["goal"]:
            st.success("🎉 Цель достигнута!")
        elif months_to_goal >= 240 or (monthly_addition <= 0 and daily_rate == 0):
            caption += " · при текущем темпе цель не достигается"
        else:
            estimated_date = today + dt.timedelta(days=int(months_to_goal * 30.4))
            caption += f" · ориентир достижения цели: {months_to_goal} мес. ({estimated_date:%m.%Y})"
        st.caption(caption)
        with st.expander("Как считается ориентир достижения цели"):
            st.markdown(
                "Это **прогноз, а не обещание**: когда накопления дойдут до цели, если жить в нынешнем режиме и откладывать все свободные деньги.\n\n"
                f"1. **Свободные деньги за месяц** ≈ доход {money(mc['inc'])} − обычные траты {money(variable_daily * 30.4)} "
                f"(среднее за последние {window_days} дн. × 30,4) − обязательные платежи {money(regular_monthly)} (один раз в месяц) "
                f"+ кешбек {money(cashback_monthly)} = **{money(monthly_addition)}**.\n"
                f"2. Эта сумма каждый месяц добавляется к накоплениям (сейчас {money(balance)}), а на всё начисляются проценты по ставке {cfg['srate']:g}% годовых.\n"
                f"3. Считаем месяцы, пока сумма не дойдёт до цели {money(cfg['goal'])}: осталось набрать {money(max(cfg['goal'] - balance, 0))}.\n\n"
                "Реальные накопления — только то, что ты внёс кнопками «Отложить» и «Положить остаток». Прогноз пересчитывается вместе с твоими тратами."
            )

        st.markdown(
            f"**{month_label(current_month)}** · доход {money(mc['inc'])} · "
            f"потрачено {money(mc['sp'])} из лимита {money(cfg['cap'])}"
        )

        col_save, col_rest = st.columns(2)
        col_save.metric(
            f"Отложить {cfg['pct']:g}% дохода",
            money(mc["need"]),
            "уже отложено" if mc["need"] == 0 else f"план {money(mc['pl'])}",
            delta_color="off",
        )
        if mc["need"] > 0 and col_save.button("Отложить в накопления", key="save_percent"):
            add("sav", via="home", d=str(today), a=round(mc["need"], 2), k="p25", n=f"{cfg['pct']:g}% за {month_label(current_month)}")
            commit()

        if reserve:
            rest_note = f"с учётом обязательных −{money(reserve)}"
        elif mc["cin"]:
            rest_note = f"перенос с прошлого месяца {money(mc['cin'])}"
        else:
            rest_note = None
        col_rest.metric("Остаток после трат", money(rest_net), rest_note, delta_color="off")
        if rest_net > 0 and col_rest.button("Положить остаток", key="save_rest"):
            add("sav", via="home", d=str(today), a=round(rest_net, 2), k="rest", n=f"остаток {month_label(current_month)}")
            commit()

        days_left = calendar.monthrange(today.year, today.month)[1] - today.day
        if rest_net > 0:
            st.caption(f"≈ {money(rest_net / (days_left + 1))} в день до конца месяца — столько реально можно потратить.")
        elif rest_net < 0:
            st.warning(f"Не хватает {money(-rest_net)}: с учётом обязательных платежей этого месяца ты уходишь в минус.")

        if pending:
            with st.expander(f"Обязательные платежи впереди: {money(reserve)} (уже вычтены из остатка)"):
                for item in pending:
                    icon, _, _ = style_of(item.get("c"))
                    st.write(f"{icon} {item.get('c')} — {money(item.get('a'))} (до {int(item.get('day', 1))}-го числа)")
                st.caption("Список меняется в разделе «Группы» → «Регулярные платежи».")
        else:
            st.caption("Добавь ипотеку, связь и подписки в «Группы» → «Регулярные платежи» — они будут вычитаться из остатка с 1-го числа.")

        if days_left < 3 and rest_net > 0:
            st.info("Конец месяца — можно положить остаток в накопления. Если не откладывать, он перейдёт на следующий месяц.")

        today_spend = sum_between(EV, today, today)
        today_regular = sum_between(E[E["reg"]], today, today)
        st.metric(
            "Сегодня потрачено",
            money(today_spend),
            f"{today_spend - daily_limit:+,.0f} ₽ к дневному ориентиру {money(daily_limit)}".replace(",", " "),
            delta_color="inverse",
        )
        if today_regular:
            st.caption(f"Обязательные платежи сегодня ({money(today_regular)}) в этот показатель не входят.")

        for message_type, message in motivation_messages():
            (st.warning if message_type == "warning" else st.info)(message)

        if D["bud"]:
            group_spending = E[E["m"] == current_month].groupby("g")["a"].sum()
            for group, limit in D["bud"].items():
                limit = safe_float(limit)
                if limit > 0:
                    used = float(group_spending.get(group, 0))
                    st.progress(
                        min(1.0, used / limit),
                        text=f"{group}: {money(used)} из {money(limit)}" + (" ⚠️" if used > limit else ""),
                    )

        st.markdown("**Последние записи**")
        for entry in D["exp"][-6:][::-1]:
            left, right = st.columns([6, 1])
            if entry.get("t") == "cb":
                label = "🎁 Кешбек"
            else:
                label = f"{style_of(entry.get('c'))[0]} {entry.get('c', 'Запись')}"
            sign = "+" if entry.get("t") in ("cb", "in") else ""
            left.write(f"{str(entry.get('d', ''))[5:]} · {label} · **{sign}{money(entry.get('a', 0))}** {entry.get('n', '')}")
            if right.button("✕", key=f"delete_exp_{entry['id']}"):
                trash("exp", entry)
                commit()


    # ========================= Внести =========================

    if page == P_ADD:
        entry_kind = st.radio(
            "Что вносим",
            ["Трата", "Кешбек", "Доп. доход", "Доход месяца", "В накопления", "Из накоплений"],
            horizontal=True,
            label_visibility="collapsed",
            key="entry_kind",
        )

        if entry_kind == "Трата":
            recent = E[E["d"] >= today - dt.timedelta(days=90)]
            frequency = recent["c"].value_counts().to_dict()
            ranked = sorted(D["cats"], key=lambda category: (-frequency.get(category, 0), category))
            picked = st.session_state.get("pick_cat")
            if picked not in D["cats"]:
                picked = ranked[0] if ranked else None
            tile_items = []

            quick = quick_expenses(6)
            if quick:
                st.caption("⚡ Быстро — одним нажатием (разные траты, самые частые)")
                with st.container(horizontal=True):
                    for index, (category, amount) in enumerate(quick):
                        key = f"quick_{index}"
                        tile_items.append((key, category))
                        if st.button(f"{style_of(category)[0]} {category} · {amount:,.0f}".replace(",", " "), key=key):
                            add("exp", via="quick", d=str(today), c=category, a=float(amount), n="", t="e")
                            commit()

            st.caption("Категория — сверху те, которыми пользуешься чаще")
            with st.container(horizontal=True):
                for category in ranked[:8]:
                    key = f"cat_{cat_ids[category]}"
                    tile_items.append((key, category))
                    if st.button(f"{style_of(category)[0]} {category}", key=key):
                        st.session_state["pick_cat"] = picked = category

            others = ranked[8:]
            if others:
                with st.expander(f"Все остальные категории ({len(others)})"):
                    for group in dict.fromkeys(D["cats"][category] for category in others):
                        st.caption(group)
                        with st.container(horizontal=True):
                            for category in [c for c in others if D["cats"][c] == group]:
                                key = f"cat_{cat_ids[category]}"
                                tile_items.append((key, category))
                                if st.button(f"{style_of(category)[0]} {category}", key=key):
                                    st.session_state["pick_cat"] = picked = category

            quick_keys = {item for item in tile_items if item[0].startswith("quick_")}
            st.html(tile_css([item for item in tile_items if item not in quick_keys], picked) + tile_css(sorted(quick_keys)))

        if entry_kind in ("Трата", "Кешбек", "Доп. доход", "В накопления", "Из накоплений"):
            if st.session_state.pop("reset_add", False):          # очистка полей после успешного добавления
                st.session_state["add_amount"] = None
                st.session_state["add_comment"] = ""
            if entry_kind == "Трата":
                if picked:
                    st.markdown(f"Категория: **{style_of(picked)[0]} {picked}** · {D['cats'][picked]}")
                else:
                    st.warning("Сначала добавь хотя бы одну категорию в разделе «Группы».")
            amount = st.number_input(
                "Сумма, ₽", min_value=0.0, value=None, step=1.0, format="%g",
                placeholder="Введи сумму, например 1250", key="add_amount",
            )
            typical = typical_amounts(picked) if (entry_kind == "Трата" and picked) else []
            if typical:
                st.caption("Частые суммы этой категории — нажми, чтобы подставить")
                with st.container(horizontal=True):
                    for index, value in enumerate(typical):
                        st.button(f"{value:,.0f}".replace(",", " "), key=f"amt_set_{index}", on_click=set_amount, args=(value,))
            st.caption("Прибавить к сумме")
            with st.container(horizontal=True):
                for step_value in (100, 500, 1000, 5000):
                    st.button(f"+{step_value:,}".replace(",", " "), key=f"amt_add_{step_value}", on_click=add_to_amount, args=(step_value,))
                st.button("Сбросить", key="amt_clear", on_click=set_amount, args=(None,))
            entry_date = st.date_input("Дата", today, key="add_date")
            comment_label = "Источник (подработка, возврат…)" if entry_kind == "Доп. доход" else "Комментарий"
            comment = st.text_input(comment_label, key="add_comment")

            if st.button("Добавить", type="primary", key="add_submit"):
                if not amount or amount <= 0:
                    log("validation_error", where="add_form", kind=entry_kind)
                    st.error("Введи сумму больше нуля.")
                elif entry_kind == "Трата" and not picked:
                    st.error("Нет доступных категорий.")
                else:
                    if entry_kind == "Трата":
                        add("exp", via="form", d=str(entry_date), c=picked, a=float(amount), n=comment, t="e")
                    elif entry_kind == "Кешбек":
                        add("exp", via="form", d=str(entry_date), c="Кешбек", a=float(amount), n=comment, t="cb")
                    elif entry_kind == "Доп. доход":
                        add("exp", via="form", d=str(entry_date), c="Доп. доход", a=float(amount), n=comment, t="in")
                    else:
                        add("sav", via="form", d=str(entry_date), a=float(amount), k="dep" if entry_kind == "В накопления" else "wd", n=comment)
                    st.session_state["reset_add"] = True
                    commit()

            if entry_kind == "Кешбек":
                st.caption("Кешбек учитывается как поступление в накопления.")
            elif entry_kind == "Из накоплений":
                st.caption("Снятие уменьшает накопления и увеличивает свободные деньги месяца.")

        if entry_kind == "Доход месяца":
            next_year, next_month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            months = sorted(set(list(monthly) + list(D["inc"]) + [f"{next_year}-{next_month:02d}"]), reverse=True)
            selected_month = st.selectbox("Месяц дохода", months, format_func=month_label, key="income_month_select")
            income_key = "income_value_" + selected_month
            income_value = st.number_input(
                "Основной доход за этот месяц, ₽", min_value=0.0,
                value=float(D["inc"].get(selected_month, cfg["income"])), step=1000.0, key=income_key,
            )
            save_col, reset_col = st.columns(2)
            if save_col.button("Сохранить доход месяца", type="primary", key="save_month_income"):
                D["inc"][selected_month] = float(income_value)
                log("income_month_set", month=selected_month, amount=float(income_value))
                commit()
            if selected_month in D["inc"] and reset_col.button("Сбросить к стандартному", key="reset_month_income"):
                del D["inc"][selected_month]
                st.session_state.pop(income_key, None)
                log("income_month_reset", month=selected_month)
                commit()
            st.caption(f"Стандартный доход: {money(cfg['income'])}. Дополнительные доходы вносятся отдельно и прибавляются.")


    # ========================= Аналитика =========================

    if page == P_AN:
        available_months = sorted(set(E["m"].tolist()) | {current_month}, reverse=True)
        selected = st.selectbox("Месяц анализа", available_months, format_func=month_label, label_visibility="collapsed", key="analytics_month")

        year, month_number = map(int, selected.split("-"))
        days_in_month = calendar.monthrange(year, month_number)[1]
        month_start = dt.date(year, month_number, 1)
        month_end = min(dt.date(year, month_number, days_in_month), today)
        elapsed_days = max(1, (month_end - month_start).days + 1)

        prev_end = month_start - one_day
        prev_start = prev_end.replace(day=1)
        prev_cut = min(prev_start + dt.timedelta(days=elapsed_days - 1), prev_end)
        previous_month = prev_start.strftime("%Y-%m")

        current_expenses = E[E["m"] == selected]
        previous_expenses = E[E["m"] == previous_month]
        previous_same = E[(E["d"] >= prev_start) & (E["d"] <= prev_cut)]

        spent = float(current_expenses["a"].sum())
        current_var = current_expenses[~current_expenses["reg"]]
        previous_same_var = previous_same[~previous_same["reg"]]
        variable_spent = float(current_var["a"].sum())
        regular_spent = spent - variable_spent
        previous_same_total = float(previous_same_var["a"].sum())
        mandatory, flexible = regular_spent, variable_spent
        month_income = (
            monthly[selected]["inc"] if selected in monthly
            else safe_float(D["inc"].get(selected, cfg["income"]), cfg["income"]) + float(I.loc[I["m"] == selected, "a"].sum())
        )
        saved = (
            float(S.loc[(S["m"] == selected) & (S["k"] != "wd"), "a"].sum())
            + float(C.loc[C["m"] == selected, "a"].sum())
            - float(S.loc[(S["m"] == selected) & (S["k"] == "wd"), "a"].sum())
        )
        save_rate = saved / month_income * 100 if month_income else 0.0
        pending_here = reserve if selected == current_month else 0.0          # обязательные, которые ещё впереди
        var_limit = max(cfg["cap"] - regular_spent - pending_here, 0.0)       # лимит на обычные траты
        pace_plan = var_limit * elapsed_days / days_in_month
        variable_projection = variable_spent / elapsed_days * days_in_month if selected == current_month else variable_spent
        projection = regular_spent + pending_here + variable_projection       # обязательные учитываются один раз

        kpi1, kpi2 = st.columns(2)
        kpi1.metric("Потрачено", money(spent), f"обычные {money(variable_spent)} · {variable_spent - previous_same_total:+,.0f} ₽ к {month_label(previous_month)}".replace(",", " "), delta_color="off")
        kpi2.metric("Темп к лимиту", f"{variable_spent / pace_plan * 100:.0f}%" if pace_plan else "—", f"{variable_spent - pace_plan:+,.0f} ₽ к плану на сегодня".replace(",", " "), delta_color="inverse")
        kpi3, kpi4 = st.columns(2)
        kpi3.metric("Прогноз месяца" if selected == current_month else "Итог месяца", money(projection), f"{projection - cfg['cap']:+,.0f} ₽ к лимиту {money(cfg['cap'])}".replace(",", " "), delta_color="inverse")
        kpi4.metric("Отложено", money(saved), f"{save_rate:.0f}% дохода · цель {cfg['pct']:g}%", delta_color="off")

        with st.expander("Как читать эти цифры"):
            st.markdown(
                "- **Потрачено** — все траты месяца; ниже «обычные» — без обязательных платежей (ипотека, связь и т.п.) и их разница с прошлым месяцем за те же дни.\n"
                "- **Темп к лимиту** — обычные траты против плана на сегодня: 100% значит, что идёшь ровно по лимиту, меньше — экономишь. Лимит на обычные траты = лимит месяца − обязательные платежи.\n"
                "- **Прогноз месяца** = уже потраченные обязательные + ещё предстоящие обязательные (один раз) + обычные траты в нынешнем темпе до конца месяца. Ипотека и другие крупные платежи в прогнозе не повторяются.\n"
                "- **Отложено** — сколько реально ушло в накопления (с кешбеком) и какую долю дохода это составляет против цели."
            )

        st.markdown("**Последние 7 дней** (без обязательных платежей)")
        week_days = [today - dt.timedelta(days=i) for i in range(6, -1, -1)]
        weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        labels7 = [f"{weekday_names[d.weekday()]} {d.day}" for d in week_days]
        this_week = [sum_between(EV, d, d) for d in week_days]
        week_before = [sum_between(EV, d - dt.timedelta(days=7), d - dt.timedelta(days=7)) for d in week_days]
        last7 = pd.DataFrame({"День": labels7, "Траты": this_week, "Неделей ранее": week_before})
        st.altair_chart(
            alt.Chart(last7).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                x=alt.X("День:N", sort=labels7, title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("Траты:Q", title=None),
                color=alt.condition(alt.datum["Траты"] > daily_limit, alt.value(RED), alt.value(GREEN)),
                tooltip=["День", "Траты", "Неделей ранее"],
            ).properties(height=170),
            width="stretch",
        )
        st.caption(f"Обычные траты за каждый из последних 7 дней. Красный — выше дневного ориентира ({money(daily_limit)}).")

        pct_values = [round(cur / prev * 100, 1) if prev > 0 else None for cur, prev in zip(this_week, week_before)]
        pct7 = pd.DataFrame({"День": labels7, "Процент": pct_values})
        st.markdown("**К тому же дню прошлой недели, %**")
        if pct7["Процент"].notna().any():
            base_pct = alt.Chart(pct7.dropna()).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                x=alt.X("День:N", sort=labels7, title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("Процент:Q", title=None),
                color=alt.condition(alt.datum["Процент"] > 100, alt.value(RED), alt.value(GREEN)), tooltip=["День", "Процент"],
            )
            pct_text = alt.Chart(pct7.dropna()).mark_text(dy=-6).encode(x=alt.X("День:N", sort=labels7), y="Процент:Q", text=alt.Text("Процент:Q", format=".0f"))
            rule100 = alt.Chart(pd.DataFrame({"y": [100]})).mark_rule(strokeDash=[5, 4], color="#9ca3af").encode(y="y:Q")
            st.altair_chart((base_pct + pct_text + rule100).properties(height=190), width="stretch")
            missing = [label for label, value in zip(labels7, pct_values) if value is None]
            st.caption("100% — столько же, сколько в этот день неделей раньше; выше 100% (красный) — потратил больше, ниже (зелёный) — меньше." + (f" Нет данных для сравнения: {', '.join(missing)}." if missing else ""))
        else:
            st.caption("Не с чем сравнивать: неделей ранее обычных трат не было.")

        st.markdown("**Где уходят деньги**")
        by_group = current_expenses.groupby("g")["a"].sum().sort_values(ascending=False).reset_index()
        if by_group.empty:
            st.caption("В этом месяце трат пока нет.")
        else:
            by_group["Подпись"] = by_group["a"].map(lambda value: f"{money(value)} · {value / spent:.0%}")
            order_groups = list(by_group["g"])
            bars = alt.Chart(by_group).mark_bar(color=BLUE, cornerRadiusEnd=4).encode(
                y=alt.Y("g:N", sort=order_groups, title=None), x=alt.X("a:Q", title=None), tooltip=["g", "a"],
            )
            labels = alt.Chart(by_group).mark_text(align="left", dx=4).encode(y=alt.Y("g:N", sort=order_groups), x="a:Q", text="Подпись:N")
            st.altair_chart((bars + labels).properties(height=max(120, 34 * len(by_group))), width="stretch")
            st.caption(f"Обязательные: **{money(mandatory)}** ({mandatory / spent:.0%}) · гибкие: **{money(flexible)}** ({flexible / spent:.0%}). Экономить проще на гибких.")

            st.markdown("**Что изменилось к прошлому месяцу** (обычные траты, за те же дни)")
            diff = pd.DataFrame({"Сейчас": current_var.groupby("c")["a"].sum(), "Было": previous_same_var.groupby("c")["a"].sum()}).fillna(0)
            diff["Разница"] = diff["Сейчас"] - diff["Было"]
            growth = diff[diff["Разница"] > 0].sort_values("Разница", ascending=False).head(5)
            decline = diff[diff["Разница"] < 0].sort_values("Разница").head(3)
            changes = pd.concat([growth, decline]).rename_axis("Категория").reset_index()
            if changes.empty:
                st.caption("Существенных изменений нет.")
            else:
                changes["Категория"] = changes["Категория"].map(lambda value: f"{style_of(value)[0]} {value}")
                st.dataframe(changes.round(0), hide_index=True, width="stretch")
                st.caption("Сверху — категории, где траты выросли сильнее всего: первые кандидаты на экономию. Снизу — где стало меньше.")

            top_flex = current_var.groupby("c")["a"].sum().sort_values(ascending=False).head(3)
            if not top_flex.empty:
                potential = float(top_flex.sum()) * 0.2
                names = ", ".join(f"«{name}»" for name in top_flex.index)
                tip = f"💡 Если снизить {names} на 20%, за месяц останется ещё ≈ {money(potential)}"
                if monthly_addition > 0:
                    tip += f" — цель приблизится примерно на {potential * 30.4 / monthly_addition:.0f} дн."
                st.info(tip)

        st.markdown("**Обычные траты по дням месяца**")
        daily_data = pd.DataFrame({"День": range(1, days_in_month + 1)})
        daily_data["Траты"] = [
            float(current_var.loc[current_var["d"] == dt.date(year, month_number, day_number), "a"].sum())
            for day_number in daily_data["День"]
        ]
        daily_data["Накопительно"] = daily_data["Траты"].cumsum()
        daily_data["Лимит"] = [var_limit / days_in_month * day_number for day_number in daily_data["День"]]
        if selected == current_month:
            daily_data.loc[daily_data["День"] > today.day, "Накопительно"] = None
        day_limit = var_limit / days_in_month if days_in_month else 0
        st.altair_chart(
            alt.Chart(daily_data).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                x=alt.X("День:O", axis=alt.Axis(labelAngle=0, values=list(range(1, days_in_month + 1, 3)))),
                y=alt.Y("Траты:Q", title=None),
                color=alt.condition(alt.datum["Траты"] > day_limit, alt.value(RED), alt.value(GREEN)),
                tooltip=["День", "Траты"],
            ).properties(height=170),
            width="stretch",
        )
        st.caption("Без обязательных платежей. Красные дни — выше дневного лимита на обычные траты: видно, когда случаются «пробои» бюджета.")
        line_data = daily_data.melt("День", ["Накопительно", "Лимит"], "Показатель", "Значение")
        st.altair_chart(
            alt.Chart(line_data).mark_line(strokeWidth=3).encode(
                x=alt.X("День:Q", title=None), y=alt.Y("Значение:Q", title=None),
                color=alt.Color("Показатель:N", scale=alt.Scale(domain=["Накопительно", "Лимит"], range=[BLUE, "#9ca3af"]), title=None),
                strokeDash=alt.condition(alt.datum["Показатель"] == "Лимит", alt.value([5, 4]), alt.value([0])),
                tooltip=["День", "Показатель", "Значение"],
            ).properties(height=170),
            width="stretch",
        )
        st.caption("Синяя линия выше пунктирной — обычные траты идут быстрее плана, и есть риск выйти за лимит месяца.")

        weekday_window = EV[EV["d"] >= today - dt.timedelta(days=84)]
        if not weekday_window.empty:
            names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            by_weekday = weekday_window.groupby(weekday_window["d"].map(lambda value: value.weekday()))["a"].sum() / 12
            weekday_data = pd.DataFrame({"День недели": names, "В среднем": [float(by_weekday.get(index, 0)) for index in range(7)]})
            st.markdown("**В какие дни недели тратишь больше**")
            st.altair_chart(
                alt.Chart(weekday_data).mark_bar(color=BLUE, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                    x=alt.X("День недели:N", sort=names, title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("В среднем:Q", title=None), tooltip=["День недели", "В среднем"],
                ).properties(height=150),
                width="stretch",
            )
            st.caption("Средние обычные траты по дням недели за последние 12 недель — помогает понять привычки (например, выходные).")

        if not current_expenses.empty:
            st.markdown("**Крупнейшие траты месяца**")
            biggest = current_expenses.nlargest(10, "a")[["d", "c", "a", "n"]].copy()
            biggest["c"] = biggest["c"].map(lambda value: f"{style_of(value)[0]} {value}")
            st.dataframe(biggest.rename(columns={"d": "Дата", "c": "Категория", "a": "Сумма", "n": "Комментарий"}), hide_index=True, width="stretch")
            st.caption("Разовые крупные покупки обычно дают основную часть месяца — их стоит планировать заранее.")

        monthly_rows = []
        for month in sorted(set(F["m"].tolist()) | set(monthly))[-12:]:
            month_spent = float(E.loc[E["m"] == month, "a"].sum())
            month_income_value = (
                monthly[month]["inc"] if month in monthly
                else safe_float(D["inc"].get(month, cfg["income"]), cfg["income"]) + float(I.loc[I["m"] == month, "a"].sum())
            )
            month_saved = (
                float(S.loc[(S["m"] == month) & (S["k"] != "wd"), "a"].sum()) + float(C.loc[C["m"] == month, "a"].sum())
                - float(S.loc[(S["m"] == month) & (S["k"] == "wd"), "a"].sum())
            )
            monthly_rows.append({
                "Месяц": month_label(month), "Доход": month_income_value, "Траты": month_spent, "Отложено": month_saved,
                "% отложено": round(month_saved / month_income_value * 100) if month_income_value else 0,
            })
        monthly_table = pd.DataFrame(monthly_rows)
        if not monthly_table.empty:
            st.markdown("**Динамика по месяцам**")
            st.altair_chart(
                alt.Chart(monthly_table.melt("Месяц", ["Доход", "Траты", "Отложено"], "Тип", "Сумма")).mark_bar().encode(
                    x=alt.X("Месяц:N", sort=list(monthly_table["Месяц"]), title=None), y=alt.Y("Сумма:Q", title=None), xOffset="Тип:N",
                    color=alt.Color("Тип:N", scale=alt.Scale(domain=["Доход", "Траты", "Отложено"], range=[BLUE, RED, GREEN]), title=None),
                    tooltip=["Месяц", "Тип", "Сумма"],
                ).properties(height=220),
                width="stretch",
            )
            st.dataframe(monthly_table.iloc[::-1].round(0), hide_index=True, width="stretch")
            st.caption("Главный вопрос раздела: растёт ли «% отложено» до цели (25% дохода и выше) и не съедают ли траты доход.")


    # ========================= Накопления =========================

    if page == P_SAV:
        st.metric("Накоплено", money(balance), f"проценты {money(interest)}", delta_color="off")
        savings_col1, savings_col2 = st.columns(2)
        savings_col1.metric("Вложено своих", money(principal))
        savings_col2.metric("Проценты за год на текущую сумму", money(year_interest), f"≈ {money(year_interest / 12)} в месяц", delta_color="off")
        forecast_col1, forecast_col2 = st.columns(2)
        forecast_col1.metric("Доход с вклада за год (прогноз)", money(year_interest_total), "с учётом будущих взносов", delta_color="off")
        forecast_col2.metric("Накопления через год (прогноз)", money(year_balance), f"взносы +{money(year_contributions)} · проценты +{money(year_interest_total)}", delta_color="off")
        st.caption(
            f"Прогноз на 12 месяцев: сейчас {money(balance)}, каждый месяц добавляется ≈ {money(monthly_addition)} "
            f"(свободные деньги при нынешних тратах), ставка {cfg['srate']:g}% годовых с ежедневной капитализацией. "
            "Обязательные платежи учтены один раз в месяц. Это ориентир, а не обещание."
        )

        with st.expander("Ставка и стартовая сумма", expanded=False):
            with st.form("savings_settings_form"):
                new_rate = st.number_input("Ставка по накоплениям, % годовых", min_value=0.0, max_value=100.0, value=float(cfg["srate"]), step=0.5, key="set_srate")
                new_start = st.number_input("Сумма накоплений на дату старта, ₽", min_value=0.0, value=float(cfg["start"]), step=1000.0, key="set_start")
                new_sdate = st.date_input("Дата, с которой считать проценты", safe_date(cfg["sdate"], today), key="set_sdate")
                if st.form_submit_button("Сохранить", type="primary"):
                    cfg["srate"], cfg["start"], cfg["sdate"] = float(new_rate), float(new_start), str(new_sdate)
                    log("savings_settings_saved", rate=float(new_rate))
                    commit()
            st.caption("Проценты начисляются ежедневно с капитализацией; кешбек включается в накопления.")

        chart_months = sorted(monthly)[-12:]
        savings_chart = pd.DataFrame({
            "Месяц": [month_label(month) for month in chart_months],
            "Накоплено": [
                savings_engine(min(today, dt.date(int(month[:4]), int(month[5:]), calendar.monthrange(int(month[:4]), int(month[5:]))[1])))[0]
                for month in chart_months
            ],
        })
        if len(savings_chart) > 1:
            st.altair_chart(
                alt.Chart(savings_chart).mark_area(line={"color": GREEN}, opacity=0.25).encode(
                    x=alt.X("Месяц:N", sort=list(savings_chart["Месяц"]), title=None), y=alt.Y("Накоплено:Q", title=None), tooltip=["Месяц", "Накоплено"],
                ).properties(height=180),
                width="stretch",
            )

        st.markdown("**Операции**")
        operation_labels = {"dep": "Положил", "wd": "Снял", "p25": "Отложил %", "rest": "Остаток"}
        for entry in D["sav"][-15:][::-1]:
            left, right = st.columns([6, 1])
            label = operation_labels.get(entry.get("k"), entry.get("k", "Операция"))
            sign = "−" if entry.get("k") == "wd" else "+"
            left.write(f"{str(entry.get('d', ''))[5:]} · {label} · **{sign}{money(entry.get('a', 0))}** {entry.get('n', '')}")
            if right.button("✕", key=f"delete_saving_{entry['id']}"):
                trash("sav", entry)
                commit()


    # ========================= История =========================

    if page == P_HIS:
        filter_col1, filter_col2 = st.columns(2)
        date_range = filter_col1.date_input("Период", (today.replace(day=1), today), key="history_period")
        type_labels = {"Траты": "e", "Кешбеки": "cb", "Доп. доходы": "in"}
        selected_types = filter_col2.multiselect("Тип", list(type_labels), default=list(type_labels), key="history_types")
        selected_categories = st.multiselect("Категории", sorted(set(D["cats"]) | set(F["c"])), key="history_categories")
        search_text = st.text_input("Поиск по комментарию", key="history_search")

        history = F[F["t"].isin([type_labels[label] for label in selected_types])].copy()
        if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
            history = history[(history["d"] >= date_range[0]) & (history["d"] <= date_range[1])]
        if selected_categories:
            history = history[history["c"].isin(selected_categories)]
        if search_text:
            history = history[history["n"].fillna("").astype(str).str.contains(search_text, case=False, regex=False)]
        history = history.sort_values(["d", "id"], ascending=False)

        st.caption(f"Найдено: {len(history)} · траты {money(history.loc[history['t'] == 'e', 'a'].sum())}" + (" · показаны первые 300" if len(history) > 300 else ""))
        st.download_button("Скачать CSV", history[["d", "c", "a", "n", "t"]].to_csv(index=False).encode("utf-8-sig"), "expenses.csv", mime="text/csv", key="download_csv")

        editable = history.head(300)[["id", "d", "c", "a", "n"]].assign(Удалить=False).set_index("id")
        edited_history = st.data_editor(
            editable, hide_index=True, width="stretch", key="history_editor",
            column_config={
                "d": st.column_config.DateColumn("Дата"),
                "c": st.column_config.SelectboxColumn("Категория", options=sorted(set(D["cats"]) | set(F["c"]) | {"Кешбек", "Доп. доход"})),
                "a": st.column_config.NumberColumn("Сумма", min_value=0.01),
                "n": st.column_config.TextColumn("Комментарий"),
                "Удалить": st.column_config.CheckboxColumn("Удалить"),
            },
        )

        if st.button("Сохранить изменения", type="primary", key="save_history"):
            by_id = {str(entry["id"]): entry for entry in D["exp"]}
            invalid = False
            for row_id, row in edited_history.iterrows():
                entry = by_id.get(str(row_id))
                if entry is None:
                    continue
                if row["Удалить"]:
                    trash("exp", entry)
                    continue
                try:
                    amount = float(row["a"])
                    parsed_date = pd.to_datetime(row["d"], errors="raise").date()
                    category = str(row["c"]).strip()
                    if amount <= 0 or not category or category == "nan":
                        raise ValueError("Сумма должна быть положительной, категория — заполненной.")
                except Exception as error:
                    log("validation_error", where="history", error=str(error)[:120])
                    st.error(f"Проверь запись {row_id}: {error}")
                    invalid = True
                    break
                entry.update(
                    d=str(parsed_date), c=category, a=amount, n="" if pd.isna(row["n"]) else str(row["n"]),
                    t="cb" if category == "Кешбек" else "in" if category == "Доп. доход" else "e",
                )
            if not invalid:
                D["exp"].sort(key=lambda item: (item["d"], item["id"]))
                log("history_saved")
                commit()

        st.caption("Удалённые записи попадают в корзину в разделе «Ещё».")


    # ========================= Группы =========================

    if page == P_GRP:
        st.caption("Меняй группу, иконку и цвет категорий; новые категории добавляй внизу таблицы. Иконка и цвет видны на странице «Внести».")
        icon_options = ICONS + sorted({style_of(category)[0] for category in D["cats"]} - set(ICONS))
        group_rows = [
            {"Категория": category, "Группа": D["cats"][category], "Иконка": style_of(category)[0], "Цвет": style_of(category)[2]}
            for category in D["cats"]
        ]
        groups_editor = st.data_editor(
            pd.DataFrame(group_rows, columns=["Категория", "Группа", "Иконка", "Цвет"]),
            num_rows="dynamic", width="stretch", hide_index=True, key="groups_editor",
            column_config={
                "Иконка": st.column_config.SelectboxColumn("Иконка", options=icon_options),
                "Цвет": st.column_config.SelectboxColumn("Цвет", options=list(COLORS)),
            },
        )

        chips = "".join(
            f"<span style='display:inline-block;margin:2px;padding:4px 10px;border-radius:14px;border:1px solid {style_of(c)[1]};background:{style_of(c)[1]}22'>{style_of(c)[0]} {c}</span>"
            for c in D["cats"]
        )
        st.html(f"<div style='line-height:2'>{chips}</div>")

        if st.button("Сохранить группы", type="primary", key="save_groups"):
            new_categories, new_style = {}, {}
            for _, row in groups_editor.iterrows():
                category = "" if pd.isna(row["Категория"]) else str(row["Категория"]).strip()
                group = "Прочее" if pd.isna(row["Группа"]) or not str(row["Группа"]).strip() else str(row["Группа"]).strip()
                if not category:
                    continue
                new_categories[category] = group
                icon = "" if pd.isna(row.get("Иконка")) else str(row.get("Иконка"))
                color = "" if pd.isna(row.get("Цвет")) else str(row.get("Цвет"))
                if icon or color in COLORS:
                    new_style[category] = {"i": icon, "c": color if color in COLORS else ""}
            if not new_categories:
                st.error("Список пуст — изменения не сохранены.")
            else:
                D["cats"], D["style"] = new_categories, new_style
                log("groups_saved", categories=len(new_categories))
                commit()

        group_names = list(dict.fromkeys(D["cats"].values()))
        st.markdown("**Бюджеты по группам (в месяц)**")
        budget_editor = st.data_editor(
            pd.DataFrame({"Группа": group_names, "Лимит, ₽": [safe_float(D["bud"].get(group, 0)) for group in group_names]}),
            disabled=["Группа"], hide_index=True, width="stretch", key="budget_editor",
            column_config={"Лимит, ₽": st.column_config.NumberColumn("Лимит, ₽", min_value=0.0)},
        )
        if st.button("Сохранить бюджеты", key="save_budgets"):
            D["bud"] = {
                str(row["Группа"]): float(row["Лимит, ₽"]) for _, row in budget_editor.iterrows()
                if not pd.isna(row["Лимит, ₽"]) and float(row["Лимит, ₽"]) > 0
            }
            log("budgets_saved", groups=len(D["bud"]))
            commit()

        st.markdown("**Регулярные платежи** — обязательные траты: добавляются в расходы в свой день, а с 1-го числа вычитаются из остатка")
        recurring_frame = pd.DataFrame(D["rec"], columns=["c", "a", "day", "n", "last"])
        recurring_frame["a"] = pd.to_numeric(recurring_frame["a"], errors="coerce")
        recurring_frame["day"] = pd.to_numeric(recurring_frame["day"], errors="coerce")
        recurring_editor = st.data_editor(
            recurring_frame, num_rows="dynamic", hide_index=True, width="stretch", key="recurring_editor",
            column_config={
                "last": None,
                "c": st.column_config.SelectboxColumn("Категория", options=sorted(D["cats"]), required=True),
                "a": st.column_config.NumberColumn("Сумма", min_value=0.01),
                "day": st.column_config.NumberColumn("День месяца", min_value=1, max_value=31, step=1),
                "n": st.column_config.TextColumn("Комментарий"),
            },
        )
        if st.button("Сохранить регулярные", key="save_recurring"):
            recurring = []
            previous_year, previous_month_number = month_before(today.year, today.month)
            for _, row in recurring_editor.iterrows():
                if pd.isna(row["c"]) or pd.isna(row["a"]) or pd.isna(row["day"]):
                    continue
                category, amount, day_number = str(row["c"]).strip(), safe_float(row["a"]), int(row["day"])
                if not category or amount <= 0 or not 1 <= day_number <= 31:
                    continue
                last_value = row["last"]
                if isinstance(last_value, str) and re.fullmatch(r"\d{4}-\d{2}", last_value):
                    last_month = last_value
                elif day_number <= today.day:
                    last_month = current_month        # день уже прошёл: считаем, что внесено вручную (без дублей)
                else:
                    last_month = f"{previous_year}-{previous_month_number:02d}"
                recurring.append({"c": category, "a": amount, "day": day_number, "n": "" if pd.isna(row["n"]) else str(row["n"]), "last": last_month})
            D["rec"] = recurring
            log("recurring_saved", count=len(recurring))
            commit()


    # ========================= Ещё: настройки, корзина, копии, логи =========================

    if page == P_MORE:
        st.markdown("**Настройки**")
        with st.form("settings_form"):
            new_goal = st.number_input("Цель, ₽", min_value=1.0, value=float(cfg["goal"]), step=10000.0, key="set_goal")
            new_income = st.number_input("Стандартный доход в месяц, ₽", min_value=0.0, value=float(cfg["income"]), step=1000.0, key="set_income")
            new_pct = st.number_input("Откладывать, % дохода", min_value=0.0, max_value=100.0, value=float(cfg["pct"]), step=1.0, key="set_pct")
            new_cap = st.number_input("Лимит трат в месяц, ₽", min_value=0.0, value=float(cfg["cap"]), step=1000.0, key="set_cap")
            new_frm = st.date_input("Начало учёта остатков (месяц старта)", safe_date(cfg["frm"], today), key="set_frm")
            if st.form_submit_button("Сохранить настройки", type="primary"):
                cfg.update(goal=float(new_goal), income=float(new_income), pct=float(new_pct), cap=float(new_cap), frm=str(min(new_frm, today)))
                log("settings_saved")
                commit()

        st.divider()
        st.markdown("**🗑 Корзина**")
        if D["trash"]:
            if st.button("Вернуть всё удалённое", key="restore_all_trash"):
                for item in D["trash"]:
                    kind, entry = item.get("k"), item.get("e", {})
                    if kind in ("exp", "sav") and "id" in entry and str(entry["id"]) not in {str(v["id"]) for v in D[kind]}:
                        D[kind].append(entry)
                D["trash"] = []
                for key in ("exp", "sav"):
                    D[key].sort(key=lambda item: (item["d"], item["id"]))
                log("trash_restore_all")
                commit()
            for item in D["trash"][-10:][::-1]:
                left, right = st.columns([6, 1])
                entry = item.get("e", {})
                left.write(f"{entry.get('d', '')} · {entry.get('c') or entry.get('k', 'Запись')} · {money(entry.get('a', 0))} (удалено {item.get('ts', '')[:16]})")
                if right.button("↩", key=f"restore_{item.get('id')}"):
                    kind = item.get("k")
                    if kind in ("exp", "sav"):
                        D["trash"].remove(item)
                        if str(entry.get("id")) not in {str(v["id"]) for v in D[kind]}:
                            D[kind].append(entry)
                        D[kind].sort(key=lambda value: (value["d"], value["id"]))
                        log("trash_restore_one", kind=kind)
                        commit()
        else:
            st.caption("Корзина пуста.")

        st.divider()
        st.markdown("**♻️ Резервные копии**")
        st.caption("Резервная копия предыдущего состояния создаётся при каждом успешном сохранении.")
        try:
            backup_names = slist()
        except Exception as error:
            backup_names = []
            st.error(f"Не удалось получить список резервных копий: {error}")

        if backup_names:
            selected_backup = st.selectbox(
                "Версия", backup_names[:200], key="backup_select",
                format_func=lambda name: f"{name[:4]}-{name[4:6]}-{name[6:8]} {name[9:11]}:{name[11:13]}:{name[13:15]}" if len(name) >= 15 else name,
            )
            if st.button("Показать, что в копии", key="show_backup"):
                try:
                    preview_data = sget("backups/" + selected_backup)
                    if preview_data is None:
                        st.error("Файл резервной копии не найден.")
                    else:
                        st.session_state.backup_preview = migrate(preview_data)
                except Exception as error:
                    st.error(f"Не удалось прочитать копию: {error}")

            preview = st.session_state.get("backup_preview")
            if preview:
                st.info(
                    f"Записей расходов/доходов: {len(preview['exp'])} · операций накоплений: {len(preview['sav'])} · "
                    f"категорий: {len(preview['cats'])} · групп: {len(set(preview['cats'].values()))}"
                )
                restore_all_col, restore_groups_col, restore_records_col = st.columns(3)
                if restore_all_col.button("Восстановить всё", key="restore_backup_all"):
                    try:
                        remote_now = sget("data.json")
                        st.session_state.base = (remote_now or {}).get("rev", 0)
                        st.session_state.D = migrate(preview)
                        log("backup_restore", mode="all")
                        commit()
                    except Exception as error:
                        st.error(f"Не удалось восстановить копию: {error}")
                if restore_groups_col.button("Только группы и бюджеты", key="restore_backup_groups"):
                    D["cats"], D["bud"], D["rec"], D["style"] = preview["cats"], preview["bud"], preview["rec"], preview["style"]
                    log("backup_restore", mode="groups")
                    commit()
                if restore_records_col.button("Только траты и накопления", key="restore_backup_records"):
                    D["exp"], D["sav"], D["inc"] = preview["exp"], preview["sav"], preview["inc"]
                    log("backup_restore", mode="records")
                    commit()
        else:
            st.caption("Резервных копий пока нет.")

        refresh_col, download_col = st.columns(2)
        if refresh_col.button("🔄 Обновить с Яндекс.Диска", key="refresh_remote"):
            if st.session_state.get("unsaved"):
                st.error("Есть несохранённые изменения — сначала нажми «Повторить сохранение» вверху, иначе они пропадут.")
            else:
                try:
                    remote_data = sget("data.json")
                    if remote_data is None:
                        st.warning("На Яндекс.Диске пока нет основного файла.")
                    else:
                        st.session_state.D = migrate(remote_data)
                        st.session_state.base = remote_data.get("rev", 0)
                        log("refresh_remote")
                        st.rerun()
                except Exception as error:
                    log("refresh_fail", error=str(error)[:200])
                    st.error(f"Не удалось обновить данные: {error}")
        download_col.download_button("⬇️ Скачать полную копию", json.dumps(D, ensure_ascii=False, indent=2), "million-backup.json", mime="application/json", key="download_backup")

        backup_file = st.file_uploader("Восстановить из файла копии (JSON)", type="json", key="json_backup_upload")
        if backup_file and st.button("Загрузить файл в приложение", key="import_json"):
            try:
                imported = migrate(json.load(backup_file))
                st.session_state.D = merge(D, imported)
                log("import_json", exp=len(imported["exp"]))
                commit()
            except Exception as error:
                log("import_json_fail", error=str(error)[:200])
                st.error(f"Не удалось импортировать JSON: {error}")

        st.divider()
        st.markdown("**Импорт из Excel** (лист «Расходы»)")
        excel_file = st.file_uploader("Файл .xlsx", type="xlsx", key="excel_import")
        if excel_file and st.button("Импортировать", key="import_excel"):
            try:
                excel_file.seek(0)
                excel_data = pd.read_excel(excel_file, sheet_name="Расходы", header=None)
                if excel_data.empty or excel_data.shape[1] < 9:
                    raise ValueError("В листе «Расходы» недостаточно столбцов.")
                header_rows = excel_data.index[excel_data.iloc[:, 0].astype(str).str.strip() == "Дата и время"].tolist()
                if not header_rows:
                    raise ValueError("Не найдена строка заголовка «Дата и время».")

                existing = {(e.get("d"), e.get("c"), safe_float(e.get("a")), e.get("n", "")) for e in D["exp"]}
                imported_count = 0
                for _, row in excel_data.iloc[header_rows[0] + 1:].iterrows():
                    parsed_date = pd.to_datetime(row.iloc[0], errors="coerce")
                    category = "" if pd.isna(row.iloc[1]) else str(row.iloc[1]).strip()
                    amount = pd.to_numeric(row.iloc[3], errors="coerce")
                    comment = "" if pd.isna(row.iloc[8]) else str(row.iloc[8]).strip()
                    if pd.isna(parsed_date) or pd.isna(amount) or float(amount) <= 0 or not category or category in ("Накопления", "nan"):
                        continue
                    date_text = str(parsed_date.date())
                    key = (date_text, category, float(amount), comment)
                    if key in existing:
                        continue
                    D["cats"].setdefault(category, "Прочее")
                    existing.add(key)
                    add("exp", via="excel", d=date_text, c=category, a=float(amount), n=comment, t="e")
                    imported_count += 1
                st.success(f"Добавлено записей: {imported_count}")
                log("import_excel", count=imported_count)
                commit()
            except Exception as error:
                log("import_excel_fail", error=str(error)[:200])
                st.error(f"Не удалось импортировать Excel: {error}")

        st.divider()
        st.markdown("**🧾 Логи для улучшения приложения**")
        st.caption("Действия, ошибки и время работы пишутся на Яндекс.Диск в папку «logs» (по файлу на каждый сеанс). Паролей, токенов и комментариев к тратам в логах нет.")
        session_events = st.session_state.get("log_all", [])
        log_col1, log_col2 = st.columns(2)
        if log_col1.button("Отправить логи сейчас", key="flush_logs"):
            if flush_logs():
                st.success("Логи записаны на Яндекс.Диск.")
            else:
                st.error("Не удалось записать логи (они остаются в сессии).")
        log_col2.download_button("⬇️ Лог этого сеанса", json.dumps(session_events, ensure_ascii=False, indent=2), "session-log.json", mime="application/json", key="download_session_log")
        st.caption(f"Событий в этом сеансе: {len(session_events)}")
        if st.button("Собрать все логи в один файл", key="collect_logs"):
            try:
                collected = []
                for name in slist("logs")[:300]:
                    part = sget("logs/" + name)
                    if isinstance(part, dict):
                        collected.append(part)
                st.session_state["all_logs_json"] = json.dumps(collected, ensure_ascii=False, indent=2)
                st.session_state["all_logs_count"] = len(collected)
            except Exception as error:
                st.error(f"Не удалось собрать логи: {error}")
        if st.session_state.get("all_logs_json"):
            st.download_button(f"⬇️ Скачать все логи ({st.session_state.get('all_logs_count', 0)} сеансов)", st.session_state["all_logs_json"], "all-logs.json", mime="application/json", key="download_all_logs")


try:
    run_ui()
except Exception as error:            # сбой интерфейса: записываем в лог и показываем стандартную ошибку Streamlit
    log("ui_exception", error=str(error)[:300], trace=traceback.format_exc()[-1200:])
    flush_logs()
    raise
