import json
import base64
import os
import time
import random
import calendar
import datetime as dt

import requests
import pandas as pd
import altair as alt
import streamlit as st


# ========================= Настройки интерфейса =========================

st.set_page_config(page_title="Путь к миллиону", page_icon="💰")
st.markdown(
    """
    <style>
    .block-container{padding:.7rem .8rem 3rem;max-width:780px}
    h1,h2,h3{margin:0;padding:.25rem 0}
    [data-testid=stMetricValue]{font-size:1.25rem}
    [data-testid=stMetricLabel]{font-size:.8rem}
    [data-testid=stHeader]{height:1.8rem}
    div[data-testid=stVerticalBlock]{gap:.55rem}
    .stTabs [data-baseweb=tab]{padding:.4rem .5rem}
    </style>
    """,
    unsafe_allow_html=True,
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
        entered = st.text_input("Пароль", type="password")
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


def yandex_headers():
    token = sec("yandex_token")
    if not token:
        raise RuntimeError("Не задан yandex_token в Secrets")
    return {"Authorization": "OAuth " + str(token)}


def local_path(path):
    full = os.path.join(LOCAL, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    return full


def sget(path):
    if LOCAL:
        full = os.path.join(LOCAL, path)
        if not os.path.exists(full):
            return None
        with open(full, "r", encoding="utf-8") as file:
            return json.load(file)

    response = requests.get(
        YANDEX_API + "/resources/download",
        params={"path": "app:/" + path},
        headers=yandex_headers(),
        timeout=20,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()

    download = requests.get(response.json()["href"], timeout=30)
    download.raise_for_status()
    return download.json()


def sput(path, value):
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")

    if LOCAL:
        with open(local_path(path), "wb") as file:
            file.write(payload)
        return

    if not st.session_state.get("yandex_backup_dir_ready"):
        mkdir = requests.put(
            YANDEX_API + "/resources",
            params={"path": "app:/backups"},
            headers=yandex_headers(),
            timeout=20,
        )
        if mkdir.status_code not in (201, 202, 409):
            mkdir.raise_for_status()
        st.session_state.yandex_backup_dir_ready = True

    response = requests.get(
        YANDEX_API + "/resources/upload",
        params={"path": "app:/" + path, "overwrite": "true"},
        headers=yandex_headers(),
        timeout=20,
    )
    response.raise_for_status()

    upload = requests.put(response.json()["href"], data=payload, timeout=60)
    upload.raise_for_status()


def slist():
    if LOCAL:
        folder = os.path.join(LOCAL, "backups")
        if not os.path.isdir(folder):
            return []
        return sorted(
            [name for name in os.listdir(folder) if name.endswith(".json")],
            reverse=True,
        )

    response = requests.get(
        YANDEX_API + "/resources",
        params={"path": "app:/backups", "limit": 1000, "sort": "-name"},
        headers=yandex_headers(),
        timeout=20,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return [
        item["name"]
        for item in response.json().get("_embedded", {}).get("items", [])
        if item.get("type") == "file" and item.get("name", "").endswith(".json")
    ]


def uid():
    return int(time.time() * 1000) * 10 + random.randint(0, 9)


def default_data():
    return {
        "v": 2,
        "rev": 0,
        "cfg": {},
        "cats": {category: group for group, categories in G0.items() for category in categories},
        "bud": {},
        "rec": [],
        "exp": [],
        "sav": [],
        "inc": {},
        "trash": [],
    }


def migrate(data):
    """Дополняет старые версии структуры и исправляет безопасные значения."""
    if not isinstance(data, dict):
        data = default_data()

    result = dict(data)
    result.setdefault("cfg", {})
    cfg = result["cfg"] if isinstance(result["cfg"], dict) else {}
    result["cfg"] = cfg

    today = dt.date.today()
    cfg.setdefault("goal", 1_000_000)
    cfg.setdefault("income", 149_600)
    cfg.setdefault("cap", 90_000)
    cfg.setdefault("pct", cfg.get("rate", 25))
    cfg.setdefault("srate", 0.0)
    cfg.setdefault("frm", str(today))
    cfg.setdefault("start", 0.0)
    cfg.setdefault("sdate", cfg["frm"])

    defaults = {
        "cats": {category: group for group, categories in G0.items() for category in categories},
        "bud": {},
        "rec": [],
        "exp": [],
        "sav": [],
        "inc": {},
        "trash": [],
        "rev": 0,
    }
    for key, value in defaults.items():
        result.setdefault(key, value)

    # Старые записи без типа считаются обычными расходами.
    for entry in result["exp"]:
        entry.setdefault("t", "e")
        entry.setdefault("n", "")
    for entry in result["sav"]:
        entry.setdefault("n", "")

    result["v"] = 2
    return result


def merge(local_data, remote_data):
    """Объединяет записи двух устройств с учётом удалений из корзины."""
    local_data = migrate(local_data)
    remote_data = migrate(remote_data)
    out = dict(local_data)

    deleted = {
        str(item.get("id"))
        for item in local_data["trash"] + remote_data["trash"]
        if isinstance(item, dict) and "id" in item
    }

    for key in ("exp", "sav"):
        combined = {}
        for entry in remote_data[key] + local_data[key]:
            entry_id = str(entry.get("id"))
            if entry_id and entry_id not in deleted:
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

    # Локальные регулярные платежи имеют приоритет.
    out["rec"] = local_data["rec"]
    out["cfg"] = {**remote_data["cfg"], **local_data["cfg"]}
    out["rev"] = max(local_data.get("rev", 0), remote_data.get("rev", 0))
    return out


# ========================= Первичная загрузка =========================

if "D" not in st.session_state:
    if not (LOCAL or sec("yandex_token")):
        st.error("Не задан доступ к Яндекс.Диску. Добавь `yandex_token` в Secrets.")
        st.stop()

    try:
        loaded = sget("data.json")
        if loaded is None:
            backup_names = slist()
            if backup_names:
                loaded = sget("backups/" + backup_names[0])
                st.session_state.note = (
                    "Основной файл не найден — загружена последняя резервная копия."
                )
    except Exception as error:
        st.error(f"Не удалось прочитать хранилище: {error}. Данные не изменены.")
        if st.button("Повторить загрузку"):
            st.rerun()
        st.stop()

    st.session_state.D = migrate(loaded if loaded else default_data())
    st.session_state.base = (loaded or {}).get("rev", 0)


D = st.session_state.D
cfg = D["cfg"]

if st.session_state.get("note"):
    st.warning(st.session_state.pop("note"))


def save():
    """Сохраняет данные и делает резервную копию предыдущей версии."""
    try:
        remote = sget("data.json")
        current = st.session_state.D

        if remote and remote.get("rev", 0) != st.session_state.get("base", 0):
            current = merge(current, remote)
            st.session_state.D = current
            st.info("Данные изменились на другом устройстве — записи объединены.")

        if remote:
            backup_name = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".json"
            sput("backups/" + backup_name, remote)

        current["rev"] = (remote or {}).get("rev", 0) + 1
        sput("data.json", current)
        st.session_state.base = current["rev"]
        return True

    except Exception as error:
        st.error(
            f"НЕ СОХРАНЕНО: {error}. Данные пока остались в текущей сессии. "
            "Не закрывай страницу; проверь подключение и повтори действие."
        )
        return False


def commit():
    if save():
        st.rerun()
    st.stop()


def add(kind, **values):
    D[kind].append({"id": uid(), **values})
    D[kind].sort(key=lambda item: (str(item.get("d", "")), int(item.get("id", 0))))


def trash(kind, entry):
    if entry in D[kind]:
        D[kind].remove(entry)
        D["trash"].append({
            "id": entry["id"],
            "k": kind,
            "e": entry,
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
        })
        D["trash"] = D["trash"][-500:]


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


def make_frame(rows, columns):
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        frame["d"] = pd.Series(dtype="object")
        frame["a"] = pd.Series(dtype="float64")
        frame["m"] = pd.Series(dtype="object")
        return frame

    frame["d"] = pd.to_datetime(frame["d"], errors="coerce").dt.date
    frame["a"] = pd.to_numeric(frame["a"], errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["d"])
    frame["m"] = pd.to_datetime(frame["d"]).dt.strftime("%Y-%m")
    return frame


F = make_frame(D["exp"], ["id", "d", "c", "a", "n", "t"])
if "t" not in F:
    F["t"] = "e"
F["t"] = F["t"].fillna("e")
F["n"] = F["n"].fillna("")
F["g"] = F["c"].map(D["cats"]).fillna("Прочее")

S = make_frame(D["sav"], ["id", "d", "a", "k", "n"])
if "k" not in S:
    S["k"] = ""
S["n"] = S["n"].fillna("")

E = F[F["t"] == "e"].copy()
C = F[F["t"] == "cb"].copy()
I = F[F["t"] == "in"].copy()


def sum_between(frame, start, end):
    if frame.empty:
        return 0.0
    return float(frame.loc[(frame["d"] >= start) & (frame["d"] <= end), "a"].sum())


# Расчёт помесячного остатка от месяца начала учёта до текущего месяца.
monthly = {}
carry = 0.0
for month in month_range(start_month_date, today):
    year, month_number = map(int, month.split("-"))
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
        "base": base_income,
        "ex": extra_income,
        "inc": income_total,
        "pl": planned_saving,
        "sp": expenses,
        "p25": saved_percent,
        "need": amount_to_save,
        "rest": cash - amount_to_save,
        "cin": carry,
    }
    carry = cash

mc = monthly.get(current_month, {
    "base": cfg["income"], "ex": 0.0, "inc": cfg["income"],
    "pl": cfg["income"] * cfg["pct"] / 100, "sp": 0.0,
    "p25": 0.0, "need": cfg["income"] * cfg["pct"] / 100,
    "rest": 0.0, "cin": 0.0,
})


def savings_engine(until):
    flows = [(safe_date(cfg["sdate"], today), cfg["start"])]
    flows += [
        (row.d, -float(row.a) if row.k == "wd" else float(row.a))
        for row in S.itertuples()
    ]
    flows += [(row.d, float(row.a)) for row in C.itertuples()]
    flows = sorted((date, amount) for date, amount in flows if date <= until)

    if not flows:
        return 0.0, 0.0

    daily_rate = cfg["srate"] / 100.0 / 365.0
    balance = principal = 0.0
    index = 0
    date = flows[0][0]

    while date <= until:
        balance *= 1.0 + daily_rate
        while index < len(flows) and flows[index][0] == date:
            balance += flows[index][1]
            principal += flows[index][1]
            index += 1
        date += one_day

    return balance, principal


balance, principal = savings_engine(today)
interest = balance - principal
daily_rate = cfg["srate"] / 100.0 / 365.0
year_interest = balance * ((1.0 + daily_rate) ** 365 - 1.0)

first_expense = F["d"].min() if not F.empty else today
window_days = min(30, max(1, (today - first_expense).days + 1))
window_start = today - dt.timedelta(days=window_days - 1)
daily_spend = sum_between(E, window_start, today) / window_days
monthly_addition = (
    max(mc["inc"] - daily_spend * 30.4, 0.0)
    + sum_between(C, window_start, today) / window_days * 30.4
)
daily_limit = cfg["cap"] / 30.0 if cfg["cap"] else 0.0

projected_balance = balance
months_to_goal = 0
while (
    projected_balance < cfg["goal"]
    and months_to_goal < 240
    and (monthly_addition > 0 or daily_rate > 0)
):
    projected_balance = projected_balance * ((1.0 + daily_rate) ** 30.4) + monthly_addition
    months_to_goal += 1


def motivation_messages():
    messages = []
    today_spend = sum_between(E, today, today)
    yesterday_spend = sum_between(E, today - one_day, today - one_day)
    if today_spend > daily_limit:
        extra = today_spend - daily_limit
        messages.append((
            "warning",
            f"Сегодня потрачено на {money(extra)} больше дневного ориентира.",
        ))
    elif today_spend > 0:
        messages.append(("info", f"Сегодня в рамках дневного ориентира. Запас {money(daily_limit - today_spend)}."))
    else:
        messages.append(("info", "Пока нет трат за сегодня. Не забудь внести расходы вечером."))

    week_start = today - dt.timedelta(days=today.weekday())
    previous_week_start = week_start - dt.timedelta(days=7)
    elapsed = (today - week_start).days
    current_week = sum_between(E, week_start, today)
    previous_week = sum_between(E, previous_week_start, previous_week_start + dt.timedelta(days=elapsed))

    if sum_between(E, previous_week_start, week_start - one_day) > 0:
        difference = current_week - previous_week
        if difference > 0:
            messages.append(("warning", f"За неделю потрачено на {money(difference)} больше, чем за такой же период прошлой недели."))
        else:
            messages.append(("info", f"За неделю потрачено на {money(-difference)} меньше. Хорошая динамика!"))

    current_categories = (
        E.loc[(E["d"] >= week_start) & (E["g"] != "Обязательные")]
        .groupby("c")["a"].sum()
    )
    previous_categories = E.loc[
        (E["d"] >= previous_week_start) & (E["d"] <= previous_week_start + dt.timedelta(days=elapsed))
    ].groupby("c")["a"].sum()
    difference_by_category = current_categories.sub(previous_categories, fill_value=0)

    if not difference_by_category.empty and difference_by_category.max() > 500:
        category = difference_by_category.idxmax()
        amount = float(difference_by_category.max())
        messages.append(("warning", f"Сильнее всего выросла категория «{category}»: +{money(amount)}."))

    return messages


# ========================= Интерфейс =========================

st.markdown("### 💰 Путь к миллиону")
tab_home, tab_add, tab_analytics, tab_savings, tab_history, tab_groups, tab_more = st.tabs([
    "🏠 Главная", "➕ Внести", "📊 Аналитика", "💰 Накопления",
    "📜 История", "🗂 Группы", "⚙️ Ещё",
])


# ========================= Главная =========================

with tab_home:
    st.metric(
        "Накоплено (расчётная сумма)",
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
        add("sav", d=str(today), a=round(mc["need"], 2), k="p25", n=f"{cfg['pct']:g}% за {month_label(current_month)}")
        commit()

    col_rest.metric(
        "Остаток после трат",
        money(mc["rest"]),
        f"перенос с прошлого месяца {money(mc['cin'])}" if mc["cin"] else None,
        delta_color="off",
    )
    if mc["rest"] > 0 and col_rest.button("Положить остаток", key="save_rest"):
        add("sav", d=str(today), a=round(mc["rest"], 2), k="rest", n=f"остаток {month_label(current_month)}")
        commit()

    days_left = calendar.monthrange(today.year, today.month)[1] - today.day
    if days_left < 3 and mc["rest"] > 0:
        st.info("Конец месяца — можно положить остаток в накопления. Если не откладывать, он перейдёт на следующий месяц.")

    today_spend = sum_between(E, today, today)
    st.metric(
        "Сегодня потрачено",
        money(today_spend),
        f"{today_spend - daily_limit:+,.0f} ₽ к дневному ориентиру".replace(",", " "),
        delta_color="inverse",
    )

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
        label = "🎁 Кешбек" if entry.get("t") == "cb" else entry.get("c", "Запись")
        sign = "+" if entry.get("t") in ("cb", "in") else ""
        left.write(
            f"{str(entry.get('d', ''))[5:]} · {label} · "
            f"**{sign}{money(entry.get('a', 0))}** {entry.get('n', '')}"
        )
        if right.button("✕", key=f"delete_exp_{entry['id']}"):
            trash("exp", entry)
            commit()


# ========================= Внести =========================

with tab_add:
    entry_kind = st.radio(
        "Что вносим",
        ["Трата", "Кешбек", "Доп. доход", "Доход месяца", "В накопления", "Из накоплений"],
        horizontal=True,
        label_visibility="collapsed",
    )

    categories_order = sorted(
        D["cats"],
        key=lambda category: (
            list(dict.fromkeys(D["cats"].values())).index(D["cats"][category]),
            category,
        ),
    )

    if entry_kind == "Трата":
        frequent = (
            E[E["d"] >= today - dt.timedelta(days=90)]
            .groupby(["c", "a"]).size().reset_index(name="count")
            .query("count >= 2").sort_values("count", ascending=False).head(6)
        )
        if not frequent.empty:
            quick_columns = st.columns(3)
            for index, row in enumerate(frequent.itertuples(index=False)):
                if quick_columns[index % 3].button(
                    f"{row.c} · {row.a:.0f}",
                    key=f"quick_expense_{index}",
                ):
                    add("exp", d=str(today), c=row.c, a=float(row.a), n="", t="e")
                    commit()

    if entry_kind in ("Трата", "Кешбек", "Доп. доход", "В накопления", "Из накоплений"):
        with st.form("add_entry_form", clear_on_submit=True):
            amount = st.number_input("Сумма, ₽", min_value=0.0, step=100.0)
            entry_date = st.date_input("Дата", today)

            category = None
            if entry_kind == "Трата":
                if not categories_order:
                    st.warning("Сначала добавь хотя бы одну категорию во вкладке «Группы».")
                else:
                    category = st.selectbox(
                        "Категория",
                        categories_order,
                        format_func=lambda value: f"{D['cats'][value]} · {value}",
                    )

            comment_label = "Источник (подработка, возврат…)" if entry_kind == "Доп. доход" else "Комментарий"
            comment = st.text_input(comment_label)

            submitted = st.form_submit_button("Добавить", type="primary")
            if submitted:
                if amount <= 0:
                    st.error("Сумма должна быть больше нуля.")
                elif entry_kind == "Трата":
                    if category is None:
                        st.error("Нет доступных категорий.")
                    else:
                        add("exp", d=str(entry_date), c=category, a=float(amount), n=comment, t="e")
                        commit()
                elif entry_kind == "Кешбек":
                    add("exp", d=str(entry_date), c="Кешбек", a=float(amount), n=comment, t="cb")
                    commit()
                elif entry_kind == "Доп. доход":
                    add("exp", d=str(entry_date), c="Доп. доход", a=float(amount), n=comment, t="in")
                    commit()
                else:
                    operation = "dep" if entry_kind == "В накопления" else "wd"
                    add("sav", d=str(entry_date), a=float(amount), k=operation, n=comment)
                    commit()

        if entry_kind == "Кешбек":
            st.caption("Кешбек учитывается как поступление в накопления.")
        elif entry_kind == "Из накоплений":
            st.caption("Снятие уменьшает накопления и увеличивает свободные деньги месяца.")

    if entry_kind == "Доход месяца":
        months = sorted(set(list(monthly) + list(D["inc"])), reverse=True)
        if not months:
            months = [current_month]
        selected_month = st.selectbox("Месяц", months, format_func=month_label)
        income_value = st.number_input(
            "Основной доход за этот месяц, ₽",
            min_value=0.0,
            value=float(D["inc"].get(selected_month, cfg["income"])),
            step=1000.0,
            key="income_" + selected_month,
        )
        save_col, reset_col = st.columns(2)
        if save_col.button("Сохранить доход месяца", type="primary"):
            D["inc"][selected_month] = income_value
            commit()
        if selected_month in D["inc"] and reset_col.button("Сбросить к стандартному"):
            del D["inc"][selected_month]
            commit()
        st.caption(f"Стандартный доход: {money(cfg['income'])}. Дополнительные доходы вносятся отдельно и прибавляются.")


# ========================= Аналитика =========================

with tab_analytics:
    available_months = sorted(set(E["m"].tolist()) | {current_month}, reverse=True)
    selected = st.selectbox("Месяц", available_months, format_func=month_label, label_visibility="collapsed")

    year, month_number = map(int, selected.split("-"))
    days_in_month = calendar.monthrange(year, month_number)[1]
    month_start = dt.date(year, month_number, 1)
    month_end = min(dt.date(year, month_number, days_in_month), today)
    elapsed_days = max(1, (month_end - month_start).days + 1)

    previous_month = (month_start - one_day).strftime("%Y-%m")
    current_expenses = E[E["m"] == selected]
    previous_expenses = E[E["m"] == previous_month]
    spent = float(current_expenses["a"].sum())
    previous_spent = float(previous_expenses["a"].sum())

    month_income = (
        monthly[selected]["inc"]
        if selected in monthly
        else safe_float(D["inc"].get(selected, cfg["income"]), cfg["income"])
        + float(I.loc[I["m"] == selected, "a"].sum())
    )
    projection = spent / elapsed_days * days_in_month if selected == current_month else spent

    metric_a, metric_b = st.columns(2)
    metric_a.metric("Потрачено", money(spent), f"{spent - previous_spent:+,.0f} ₽ к {month_label(previous_month)}".replace(",", " "), delta_color="inverse")
    metric_b.metric("В день", money(spent / elapsed_days))

    metric_c, metric_d = st.columns(2)
    metric_c.metric("Прогноз месяца" if selected == current_month else "Итог месяца", money(projection), f"{projection - cfg['cap']:+,.0f} ₽ к лимиту".replace(",", " "), delta_color="inverse")
    metric_d.metric("Доля дохода", f"{spent / month_income * 100:.0f}%" if month_income else "—", f"доход {money(month_income)}", delta_color="off")

    daily_data = pd.DataFrame({"День": range(1, days_in_month + 1)})
    daily_data["Траты"] = [
        float(current_expenses.loc[current_expenses["d"] == dt.date(year, month_number, day_number), "a"].sum())
        for day_number in daily_data["День"]
    ]
    daily_data["Накопительно"] = daily_data["Траты"].cumsum()
    daily_data["Лимит"] = [cfg["cap"] / days_in_month * day_number for day_number in daily_data["День"]]

    if selected == current_month:
        daily_data.loc[daily_data["День"] > today.day, "Накопительно"] = None

    st.caption("Траты по дням (красный — выше дневного лимита)")
    st.altair_chart(
        alt.Chart(daily_data)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("День:O", axis=alt.Axis(labelAngle=0, values=list(range(1, days_in_month + 1, 3)))),
            y=alt.Y("Траты:Q", title=None),
            color=alt.condition(
                alt.datum["Траты"] > (cfg["cap"] / days_in_month if days_in_month else 0),
                alt.value(RED), alt.value(GREEN),
            ),
            tooltip=["День", "Траты"],
        )
        .properties(height=170),
        width="stretch",
    )

    st.caption("Нарастающим итогом против плана по лимиту")
    line_data = daily_data.melt("День", ["Накопительно", "Лимит"], "Показатель", "Значение")
    st.altair_chart(
        alt.Chart(line_data)
        .mark_line(strokeWidth=3)
        .encode(
            x=alt.X("День:Q", title=None),
            y=alt.Y("Значение:Q", title=None),
            color=alt.Color(
                "Показатель:N",
                scale=alt.Scale(domain=["Накопительно", "Лимит"], range=[BLUE, "#9ca3af"]),
                title=None,
            ),
            strokeDash=alt.condition(alt.datum["Показатель"] == "Лимит", alt.value([5, 4]), alt.value([0])),
            tooltip=["День", "Показатель", "Значение"],
        )
        .properties(height=170),
        width="stretch",
    )

    group_pie = current_expenses.groupby("g")["a"].sum().reset_index()
    if not group_pie.empty:
        st.caption("Структура расходов по группам")
        st.altair_chart(
            alt.Chart(group_pie)
            .mark_arc(innerRadius=60)
            .encode(theta="a:Q", color=alt.Color("g:N", title=None, scale=alt.Scale(scheme="tableau10")), tooltip=["g", "a"])
            .properties(height=220),
            width="stretch",
        )

        category_compare = (
            pd.concat([
                current_expenses.groupby("c")["a"].sum().rename("Этот месяц"),
                previous_expenses.groupby("c")["a"].sum().rename("Прошлый"),
            ], axis=1)
            .fillna(0).sort_values("Этот месяц", ascending=False).head(10).reset_index()
        )
        st.caption("Топ-10 категорий: этот и прошлый месяц")
        st.altair_chart(
            alt.Chart(category_compare.melt("c", ["Этот месяц", "Прошлый"], "Период", "Сумма"))
            .mark_bar()
            .encode(
                y=alt.Y("c:N", sort=list(category_compare["c"]), title=None),
                x=alt.X("Сумма:Q", title=None),
                yOffset="Период:N",
                color=alt.Color("Период:N", scale=alt.Scale(domain=["Этот месяц", "Прошлый"], range=[GREEN, "#cbd5e1"]), title=None),
                tooltip=["c", "Период", "Сумма"],
            )
            .properties(height=max(200, 34 * len(category_compare))),
            width="stretch",
        )

        st.caption("Крупнейшие траты месяца")
        st.dataframe(
            current_expenses.nlargest(10, "a")[["d", "c", "a", "n"]].rename(
                columns={"d": "Дата", "c": "Категория", "a": "Сумма", "n": "Комментарий"}
            ),
            hide_index=True,
            width="stretch",
        )

    monthly_rows = []
    months_for_table = sorted(set(F["m"].tolist()) | set(monthly))[-12:]
    for month in months_for_table:
        month_spent = float(E.loc[E["m"] == month, "a"].sum())
        month_income_value = (
            monthly[month]["inc"] if month in monthly
            else safe_float(D["inc"].get(month, cfg["income"]), cfg["income"])
            + float(I.loc[I["m"] == month, "a"].sum())
        )
        saved = (
            float(S.loc[(S["m"] == month) & (S["k"] != "wd"), "a"].sum())
            + float(C.loc[C["m"] == month, "a"].sum())
            - float(S.loc[(S["m"] == month) & (S["k"] == "wd"), "a"].sum())
        )
        monthly_rows.append({
            "Месяц": month_label(month),
            "Доход": month_income_value,
            "Траты": month_spent,
            "Отложено": saved,
            "% отложено": round(saved / month_income_value * 100) if month_income_value else 0,
        })

    monthly_table = pd.DataFrame(monthly_rows)
    st.caption("Динамика по месяцам")
    if not monthly_table.empty:
        st.altair_chart(
            alt.Chart(monthly_table.melt("Месяц", ["Доход", "Траты", "Отложено"], "Тип", "Сумма"))
            .mark_bar()
            .encode(
                x=alt.X("Месяц:N", sort=list(monthly_table["Месяц"]), title=None),
                y=alt.Y("Сумма:Q", title=None),
                xOffset="Тип:N",
                color=alt.Color("Тип:N", scale=alt.Scale(domain=["Доход", "Траты", "Отложено"], range=[BLUE, RED, GREEN]), title=None),
                tooltip=["Месяц", "Тип", "Сумма"],
            )
            .properties(height=220),
            width="stretch",
        )
        st.dataframe(monthly_table.iloc[::-1].round(0), hide_index=True, width="stretch")


# ========================= Накопления =========================

with tab_savings:
    st.metric("Накоплено", money(balance), f"проценты {money(interest)}", delta_color="off")
    savings_col1, savings_col2 = st.columns(2)
    savings_col1.metric("Вложено своих", money(principal))
    savings_col2.metric("Доход за год при текущей сумме", money(year_interest), f"≈ {money(year_interest / 12)} в месяц", delta_color="off")

    with st.expander("Ставка и стартовая сумма", expanded=False):
        cfg["srate"] = st.number_input("Ставка по накоплениям, % годовых", min_value=0.0, max_value=100.0, value=float(cfg["srate"]), step=0.5)
        cfg["start"] = st.number_input("Сумма накоплений на дату старта, ₽", min_value=0.0, value=float(cfg["start"]), step=1000.0)
        cfg["sdate"] = str(st.date_input("Дата, с которой считать проценты", safe_date(cfg["sdate"], today)))
        if st.button("Сохранить", key="save_savings_settings", type="primary"):
            commit()
        st.caption("Проценты начисляются ежедневно с капитализацией; кешбек включается в накопления.")

    chart_months = sorted(monthly)[-12:]
    savings_chart = pd.DataFrame({
        "Месяц": [month_label(month) for month in chart_months],
        "Накоплено": [
            savings_engine(min(today, dt.date(
                int(month[:4]), int(month[5:]),
                calendar.monthrange(int(month[:4]), int(month[5:]))[1],
            )))[0]
            for month in chart_months
        ],
    })
    if len(savings_chart) > 1:
        st.altair_chart(
            alt.Chart(savings_chart)
            .mark_area(line={"color": GREEN}, opacity=0.25)
            .encode(
                x=alt.X("Месяц:N", sort=list(savings_chart["Месяц"]), title=None),
                y=alt.Y("Накоплено:Q", title=None),
                tooltip=["Месяц", "Накоплено"],
            )
            .properties(height=180),
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

with tab_history:
    filter_col1, filter_col2 = st.columns(2)
    date_range = filter_col1.date_input("Период", (today.replace(day=1), today))
    type_labels = {"Траты": "e", "Кешбеки": "cb", "Доп. доходы": "in"}
    selected_types = filter_col2.multiselect("Тип", list(type_labels), default=list(type_labels))
    selected_categories = st.multiselect("Категории", sorted(D["cats"]))
    search_text = st.text_input("Поиск по комментарию")

    history = F[F["t"].isin([type_labels[label] for label in selected_types])].copy()
    if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        history = history[(history["d"] >= date_range[0]) & (history["d"] <= date_range[1])]
    if selected_categories:
        history = history[history["c"].isin(selected_categories)]
    if search_text:
        history = history[history["n"].fillna("").astype(str).str.contains(search_text, case=False, regex=False)]
    history = history.sort_values(["d", "id"], ascending=False)

    st.caption(f"Найдено: {len(history)} · траты {money(history.loc[history['t'] == 'e', 'a'].sum())}" + (" · показаны первые 300" if len(history) > 300 else ""))

    st.download_button(
        "Скачать CSV",
        history[["d", "c", "a", "n", "t"]].to_csv(index=False).encode("utf-8-sig"),
        "expenses.csv",
        mime="text/csv",
    )

    editable = (
        history.head(300)[["id", "d", "c", "a", "n"]]
        .assign(Удалить=False)
        .set_index("id")
    )
    edited_history = st.data_editor(
        editable,
        hide_index=True,
        width="stretch",
        key="history_editor",
        column_config={
            "d": st.column_config.DateColumn("Дата"),
            "c": st.column_config.SelectboxColumn("Категория", options=sorted(set(D["cats"]) | {"Кешбек", "Доп. доход"})),
            "a": st.column_config.NumberColumn("Сумма", min_value=0.01),
            "n": st.column_config.TextColumn("Комментарий"),
            "Удалить": st.column_config.CheckboxColumn("Удалить"),
        },
    )

    if st.button("Сохранить изменения", type="primary"):
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
                if amount <= 0 or not category:
                    raise ValueError("Сумма должна быть положительной, категория — заполненной.")
            except Exception as error:
                st.error(f"Проверь запись {row_id}: {error}")
                invalid = True
                break

            entry.update(
                d=str(parsed_date),
                c=category,
                a=amount,
                n="" if pd.isna(row["n"]) else str(row["n"]),
                t="cb" if category == "Кешбек" else "in" if category == "Доп. доход" else "e",
            )
        if not invalid:
            D["exp"].sort(key=lambda item: (item["d"], item["id"]))
            commit()

    st.caption("Удалённые записи попадают в корзину во вкладке «Ещё».")


# ========================= Группы и регулярные платежи =========================

with tab_groups:
    st.caption("Меняй группу у категории и добавляй новые категории внизу таблицы. Пустая группа будет заменена на «Прочее».")

    groups_editor = st.data_editor(
        pd.DataFrame({"Категория": list(D["cats"]), "Группа": list(D["cats"].values())}),
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        key="groups_editor",
    )

    if st.button("Сохранить группы", type="primary"):
        new_categories = {}
        for _, row in groups_editor.iterrows():
            category = "" if pd.isna(row["Категория"]) else str(row["Категория"]).strip()
            group = "Прочее" if pd.isna(row["Группа"]) or not str(row["Группа"]).strip() else str(row["Группа"]).strip()
            if category:
                new_categories[category] = group
        if not new_categories:
            st.error("Список пуст — изменения не сохранены.")
        else:
            D["cats"] = new_categories
            commit()

    group_names = list(dict.fromkeys(D["cats"].values()))
    st.markdown("**Бюджеты по группам (в месяц)**")
    budget_editor = st.data_editor(
        pd.DataFrame({"Группа": group_names, "Лимит, ₽": [safe_float(D["bud"].get(group, 0)) for group in group_names]}),
        disabled=["Группа"],
        hide_index=True,
        width="stretch",
        key="budget_editor",
        column_config={"Лимит, ₽": st.column_config.NumberColumn("Лимит, ₽", min_value=0.0)},
    )
    if st.button("Сохранить бюджеты"):
        D["bud"] = {
            str(row["Группа"]): float(row["Лимит, ₽"])
            for _, row in budget_editor.iterrows()
            if not pd.isna(row["Лимит, ₽"]) and float(row["Лимит, ₽"]) > 0
        }
        commit()

    st.markdown("**Регулярные платежи** (автоматически добавляются в расходы)")
    recurring_frame = pd.DataFrame(D["rec"], columns=["c", "a", "day", "n", "last"])
    if recurring_frame.empty:
        recurring_frame = pd.DataFrame(columns=["c", "a", "day", "n", "last"])
    recurring_frame["a"] = pd.to_numeric(recurring_frame["a"], errors="coerce")
    recurring_frame["day"] = pd.to_numeric(recurring_frame["day"], errors="coerce")

    recurring_editor = st.data_editor(
        recurring_frame,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key="recurring_editor",
        column_config={
            "last": None,
            "c": st.column_config.SelectboxColumn("Категория", options=sorted(D["cats"]), required=True),
            "a": st.column_config.NumberColumn("Сумма", min_value=0.01),
            "day": st.column_config.NumberColumn("День месяца", min_value=1, max_value=31, step=1),
            "n": st.column_config.TextColumn("Комментарий"),
        },
    )

    if st.button("Сохранить регулярные"):
        recurring = []
        previous_year, previous_month = month_before(today.year, today.month)
        previous_month_text = f"{previous_year}-{previous_month:02d}"

        for _, row in recurring_editor.iterrows():
            if pd.isna(row["c"]) or pd.isna(row["a"]) or pd.isna(row["day"]):
                continue
            category = str(row["c"]).strip()
            amount = safe_float(row["a"])
            day_number = int(row["day"])
            if not category or amount <= 0 or not 1 <= day_number <= 31:
                continue

            last_value = row["last"]
            if isinstance(last_value, str) and re.fullmatch(r"\d{4}-\d{2}", last_value):
                last_month = last_value
            else:
                # Для новой записи текущий месяц ещё не начислен.
                last_month = previous_month_text

            recurring.append({
                "c": category,
                "a": amount,
                "day": day_number,
                "n": "" if pd.isna(row["n"]) else str(row["n"]),
                "last": last_month,
            })

        D["rec"] = recurring
        commit()


# ========================= Ещё: настройки, корзина, резервные копии =========================

with tab_more:
    st.markdown("**Настройки**")
    cfg["goal"] = st.number_input("Цель, ₽", min_value=1.0, value=float(cfg["goal"]), step=10000.0)
    cfg["income"] = st.number_input("Стандартный доход в месяц, ₽", min_value=0.0, value=float(cfg["income"]), step=1000.0)
    cfg["pct"] = st.number_input("Откладывать, % дохода", min_value=0.0, max_value=100.0, value=float(cfg["pct"]), step=1.0)
    cfg["cap"] = st.number_input("Лимит трат в месяц, ₽", min_value=0.0, value=float(cfg["cap"]), step=1000.0)
    cfg["frm"] = str(st.date_input("Начало учёта остатков (месяц старта)", safe_date(cfg["frm"], today)))

    if st.button("Сохранить настройки", type="primary"):
        commit()

    st.divider()
    st.markdown("**🗑 Корзина**")

    if D["trash"]:
        if st.button("Вернуть всё удалённое"):
            for item in D["trash"]:
                kind = item.get("k")
                entry = item.get("e", {})
                if kind in ("exp", "sav") and "id" in entry:
                    existing_ids = {str(value["id"]) for value in D[kind]}
                    if str(entry["id"]) not in existing_ids:
                        D[kind].append(entry)
            D["trash"] = []
            for key in ("exp", "sav"):
                D[key].sort(key=lambda item: (item["d"], item["id"]))
            commit()

        for item in D["trash"][-10:][::-1]:
            left, right = st.columns([6, 1])
            entry = item.get("e", {})
            left.write(
                f"{entry.get('d', '')} · {entry.get('c') or entry.get('k', 'Запись')} · "
                f"{money(entry.get('a', 0))} (удалено {item.get('ts', '')[:16]})"
            )
            if right.button("↩", key=f"restore_{item.get('id')}"):
                kind = item.get("k")
                if kind in ("exp", "sav"):
                    D["trash"].remove(item)
                    if str(entry.get("id")) not in {str(value["id"]) for value in D[kind]}:
                        D[kind].append(entry)
                    D[kind].sort(key=lambda value: (value["d"], value["id"]))
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
            "Версия",
            backup_names[:200],
            format_func=lambda name: (
                f"{name[:4]}-{name[4:6]}-{name[6:8]} "
                f"{name[9:11]}:{name[11:13]}:{name[13:15]}"
                if len(name) >= 15 else name
            ),
        )

        if st.button("Показать, что в копии"):
            try:
                preview = sget("backups/" + selected_backup)
                if preview is None:
                    st.error("Файл резервной копии не найден.")
                else:
                    st.session_state.backup_preview = migrate(preview)
            except Exception as error:
                st.error(f"Не удалось прочитать копию: {error}")

        preview = st.session_state.get("backup_preview")
        if preview:
            st.info(
                f"Записей расходов/доходов: {len(preview['exp'])} · "
                f"операций накоплений: {len(preview['sav'])} · "
                f"категорий: {len(preview['cats'])} · "
                f"групп: {len(set(preview['cats'].values()))}"
            )
            restore_all_col, restore_groups_col, restore_records_col = st.columns(3)

            if restore_all_col.button("Восстановить всё"):
                try:
                    # Синхронизируем базовую ревизию с текущим сервером,
                    # чтобы save() не объединил восстановление со старой копией.
                    remote_now = sget("data.json")
                    st.session_state.base = (remote_now or {}).get("rev", 0)
                    st.session_state.D = migrate(preview)
                    commit()
                except Exception as error:
                    st.error(f"Не удалось восстановить копию: {error}")

            if restore_groups_col.button("Только группы и бюджеты"):
                D["cats"] = preview["cats"]
                D["bud"] = preview["bud"]
                D["rec"] = preview["rec"]
                commit()

            if restore_records_col.button("Только траты и накопления"):
                D["exp"] = preview["exp"]
                D["sav"] = preview["sav"]
                D["inc"] = preview["inc"]
                commit()
    else:
        st.caption("Резервных копий пока нет.")

    refresh_col, download_col = st.columns(2)
    if refresh_col.button("🔄 Обновить с Яндекс.Диска"):
        try:
            remote_data = sget("data.json")
            if remote_data is None:
                st.warning("На Яндекс.Диске пока нет основного файла.")
            else:
                st.session_state.D = migrate(remote_data)
                st.session_state.base = remote_data.get("rev", 0)
                st.rerun()
        except Exception as error:
            st.error(f"Не удалось обновить данные: {error}")

    download_col.download_button(
        "⬇️ Скачать полную копию",
        json.dumps(D, ensure_ascii=False, indent=2),
        "million-backup.json",
        mime="application/json",
    )

    backup_file = st.file_uploader("Восстановить из файла копии (JSON)", type="json", key="json_backup_upload")
    if backup_file and st.button("Загрузить файл в приложение"):
        try:
            imported = migrate(json.load(backup_file))
            st.session_state.D = merge(D, imported)
            commit()
        except Exception as error:
            st.error(f"Не удалось импортировать JSON: {error}")

    # Импорт из GitHub оставлен как дополнительная возможность старого проекта.
    github = sec("github")
    if github:
        st.divider()
        st.markdown("**Импорт истории из старого хранилища GitHub** (разово)")
        try:
            token = github.get("token") if isinstance(github, dict) else None
            repository = github.get("repo") if isinstance(github, dict) else None
            github_path = github.get("path", "data.json") if isinstance(github, dict) else "data.json"
            if not token or not repository:
                st.warning("В Secrets для GitHub нужны поля token и repo.")
            else:
                headers = {"Authorization": "token " + str(token)}
                commits_response = requests.get(
                    f"https://api.github.com/repos/{repository}/commits",
                    params={"path": github_path, "per_page": 40},
                    headers=headers,
                    timeout=20,
                )
                commits_response.raise_for_status()
                commits = commits_response.json()
                if not isinstance(commits, list):
                    raise ValueError("GitHub вернул неожиданный формат списка версий.")

                if commits:
                    selected_commit = st.selectbox(
                        "Версия в истории Git",
                        commits,
                        format_func=lambda commit: commit.get("commit", {}).get("author", {}).get("date", "")[:16].replace("T", " "),
                    )
                    if st.button("Показать версию"):
                        content_response = requests.get(
                            f"https://api.github.com/repos/{repository}/contents/{github_path}",
                            params={"ref": selected_commit["sha"]},
                            headers=headers,
                            timeout=20,
                        )
                        content_response.raise_for_status()
                        content_json = content_response.json()
                        decoded = base64.b64decode(content_json["content"]).decode("utf-8")
                        st.session_state.github_preview = migrate(json.loads(decoded))

                    github_preview = st.session_state.get("github_preview")
                    if github_preview:
                        st.info(f"В версии записей: {len(github_preview['exp'])}, категорий: {len(github_preview['cats'])}")
                        if st.button("Добавить эти данные к текущим"):
                            st.session_state.D = merge(D, github_preview)
                            commit()
                else:
                    st.caption("В указанном репозитории не найдены версии этого файла.")
        except Exception as error:
            st.caption(f"GitHub недоступен или вернул ошибку: {error}")

    st.divider()
    st.markdown("**Импорт из Excel** (лист «Расходы»)")
    excel_file = st.file_uploader("Файл .xlsx", type="xlsx", key="excel_import")
    if excel_file and st.button("Импортировать"):
        try:
            excel_file.seek(0)
            excel_data = pd.read_excel(excel_file, sheet_name="Расходы", header=None)
            if excel_data.empty or excel_data.shape[1] < 9:
                raise ValueError("В листе «Расходы» недостаточно столбцов.")

            header_rows = excel_data.index[
                excel_data.iloc[:, 0].astype(str).str.strip() == "Дата и время"
            ].tolist()
            if not header_rows:
                raise ValueError("Не найдена строка заголовка «Дата и время».")

            data_rows = excel_data.iloc[header_rows[0] + 1:]
            existing = {
                (entry.get("d"), entry.get("c"), safe_float(entry.get("a")), entry.get("n", ""))
                for entry in D["exp"]
            }
            imported_count = 0

            for _, row in data_rows.iterrows():
                parsed_date = pd.to_datetime(row.iloc[0], errors="coerce")
                category = "" if pd.isna(row.iloc[1]) else str(row.iloc[1]).strip()
                amount = pd.to_numeric(row.iloc[3], errors="coerce")
                comment = "" if pd.isna(row.iloc[8]) else str(row.iloc[8]).strip()

                if (
                    pd.isna(parsed_date) or pd.isna(amount) or float(amount) <= 0
                    or not category or category in ("Накопления", "nan")
                ):
                    continue

                date_text = str(parsed_date.date())
                duplicate_key = (date_text, category, float(amount), comment)
                if duplicate_key in existing:
                    continue

                D["cats"].setdefault(category, "Прочее")
                existing.add(duplicate_key)
                add("exp", d=date_text, c=category, a=float(amount), n=comment, t="e")
                imported_count += 1

            st.success(f"Добавлено записей: {imported_count}")
            commit()
        except Exception as error:
            st.error(f"Не удалось импортировать Excel: {error}")


# ========================= Автоматическое добавление регулярных платежей =========================

def apply_recurring_payments():
    changed = False

    for recurring in D["rec"]:
        try:
            last_text = recurring.get("last")
            if not isinstance(last_text, str) or not re.fullmatch(r"\d{4}-\d{2}", last_text):
                previous_year, previous_month = month_before(today.year, today.month)
                year, month = previous_year, previous_month
            else:
                year, month = map(int, last_text.split("-"))

            day_number = min(31, max(1, int(recurring["day"])))
            amount = float(recurring["a"])
            if amount <= 0:
                continue

            while (year, month) < (today.year, today.month):
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)
                payment_date = dt.date(
                    year,
                    month,
                    min(day_number, calendar.monthrange(year, month)[1]),
                )

                if payment_date > today:
                    break

                # Защита от повторного начисления при повторном запуске.
                duplicate = any(
                    entry.get("t", "e") == "e"
                    and entry.get("n", "") == ("авто " + str(recurring.get("n", ""))).strip()
                    and entry.get("c") == recurring["c"]
                    and entry.get("d") == str(payment_date)
                    and abs(safe_float(entry.get("a")) - amount) < 0.001
                    for entry in D["exp"]
                )
                if not duplicate:
                    add(
                        "exp",
                        d=str(payment_date),
                        c=recurring["c"],
                        a=amount,
                        n=("авто " + str(recurring.get("n", ""))).strip(),
                        t="e",
                    )

                recurring["last"] = f"{year}-{month:02d}"
                changed = True

        except (KeyError, TypeError, ValueError):
            # Повреждённая строка регулярного платежа не должна ломать всё приложение.
            continue

    if changed:
        commit()


apply_recurring_payments()
