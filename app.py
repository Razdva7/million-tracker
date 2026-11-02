import json, base64, os, calendar, datetime as dt
import requests, pandas as pd, altair as alt, streamlit as st

st.set_page_config(page_title="Путь к миллиону", page_icon="💰")
G0 = {"Обязательные": ["Ипотека", "Кварплата", "Связь", "Страховка", "Родителям долг за ремонт и квартиру", "Учеба в вузе"],
      "Еда": ["Продукты", "Обед на работе", "Кафе", "Кофе", "Алкоголь"],
      "Транспорт": ["Проезд на работу", "Транспорт", "Такси"],
      "Здоровье и уход": ["Здоровье", "Гигиена", "Стрижка"],
      "Семья": ["Важное для любимой", "Подарки"],
      "Досуг и покупки": ["Развлечения", "Досуг", "Отпуск", "Подписка", "Одежда", "Гаджеты и техника"],
      "Прочее": ["Дом", "Другое", "Образование"]}

def sec(k):
    try: return st.secrets[k]
    except Exception: return None

pw = sec("password")
if pw and not st.session_state.get("ok"):
    if st.text_input("Пароль", type="password") == pw:
        st.session_state.ok = True; st.rerun()
    st.stop()

# ---------- хранилище: GitHub-репозиторий (если заданы secrets) или локальный файл ----------
def _h(g): return {"Authorization": "token " + g["token"], "Accept": "application/vnd.github+json"}
def _u(g): return f"https://api.github.com/repos/{g['repo']}/contents/{g.get('path', 'data.json')}"

def load():
    g = sec("github")
    if g:
        r = requests.get(_u(g), headers=_h(g), timeout=20)
        if r.ok:
            j = r.json(); st.session_state.sha = j["sha"]
            return json.loads(base64.b64decode(j["content"]).decode())
        return None
    return json.load(open("data.json", encoding="utf-8")) if os.path.exists("data.json") else None

def save():
    txt = json.dumps(st.session_state.D, ensure_ascii=False)
    g = sec("github")
    if not g:
        open("data.json", "w", encoding="utf-8").write(txt); return
    b = {"message": "update", "content": base64.b64encode(txt.encode()).decode()}
    if st.session_state.get("sha"): b["sha"] = st.session_state.sha
    r = requests.put(_u(g), headers=_h(g), json=b, timeout=20)
    if r.ok: st.session_state.sha = r.json()["content"]["sha"]
    else: st.error("Не удалось сохранить в GitHub: " + r.text[:200])

def default():
    return {"cfg": dict(goal=1000000, start=0, income=149600, rate=25, cap=90000, frm=str(dt.date.today())),
            "cats": {c: g for g, l in G0.items() for c in l}, "exp": []}

if "D" not in st.session_state:
    st.session_state.D = load() or default()
D = st.session_state.D; cfg = D["cfg"]

def commit():
    save(); st.rerun()

# ---------- данные ----------
F = pd.DataFrame(D["exp"], columns=["id", "d", "c", "a", "n", "t"])
F["d"] = pd.to_datetime(F["d"]).dt.date; F["a"] = pd.to_numeric(F["a"]); F["t"] = F["t"].fillna("e")
F["g"] = F["c"].map(D["cats"]).fillna("Прочее"); F["m"] = pd.to_datetime(F.d).dt.strftime("%Y-%m")
E, C = F[F.t == "e"], F[F.t == "cb"]
today = dt.date.today(); day = dt.timedelta(1)
R = lambda x: f"{x:,.0f} ₽".replace(",", " ")
def s(df, a, b): return float(df[(df.d >= a) & (df.d <= b)].a.sum())

frm = min(dt.date.fromisoformat(cfg["frm"]), today)
prog = cfg["start"] + s(C, frm, today) - s(E, frm, today)
d = frm
while d <= today:
    prog += cfg["income"] / calendar.monthrange(d.year, d.month)[1]; d += day
first = F.d.min() if len(F) else today
win = min(30, (today - first).days + 1); w0 = today - dt.timedelta(win - 1)
spd = s(E, w0, today) / win if win >= 7 else cfg["cap"] / 30
ds = cfg["income"] / 30.4 - spd + s(C, w0, today) / win   # накопление в день
left = cfg["goal"] - prog; lim = cfg["cap"] / 30

def motivate():
    m = []; gain = max(ds, 1)
    td, yd = s(E, today, today), s(E, today - day, today - day)
    if td > lim: m.append(("w", f"Сегодня на {R(td - lim)} больше лимита — это примерно {(td - lim) / gain:.1f} дн. задержки цели. Завтра можно отыграть."))
    elif td > 0: m.append(("i", f"Сегодня в рамках лимита, запас {R(lim - td)}. Так и приближается миллион 💪"))
    else: m.append(("i", "Пока нет трат за сегодня. Не забудь внести расходы вечером."))
    if td > yd > 0: m.append(("w", f"Это на {R(td - yd)} больше, чем вчера."))
    w = today - dt.timedelta(today.weekday()); pw0 = w - dt.timedelta(7); k = dt.timedelta((today - w).days)
    diff = s(E, w, today) - s(E, pw0, pw0 + k)
    if len(E) and s(E, pw0, w - day) > 0:
        m.append(("w", f"За неделю ты тратишь на {R(diff)} больше, чем в прошлую.") if diff > 0 else ("i", f"Неделя идёт лучше прошлой на {R(-diff)} 👍"))
    a = E[(E.d >= w) & (E.d <= today) & (E.g != "Обязательные")].groupby("c").a.sum()
    b = E[(E.d >= pw0) & (E.d <= pw0 + k)].groupby("c").a.sum()
    dd = a.sub(b, fill_value=0)
    if len(dd) and dd.max() > 500:
        m.append(("w", f"Сильнее всего выросла категория «{dd.idxmax()}» (+{R(dd.max())}). Вернуть её к прошлому уровню — приблизить цель на {dd.max() / gain:.1f} дн."))
    m.append(("i", f"Каждые 5 000 ₽ экономии приближают цель на {5000 / gain:.1f} дн."))
    return m

st.title("💰 Путь к миллиону")
t1, t2, t3, t4 = st.tabs(["🏠 Главная", "📊 Аналитика", "🗂 Группы", "⚙️ Настройки"])

with t1:
    st.metric("Накоплено на сегодня", R(prog), f"{prog / cfg['goal'] * 100:.1f}% от {R(cfg['goal'])}")
    st.progress(max(0.0, min(1.0, prog / cfg["goal"])))
    if left <= 0: st.success("🎉 Цель достигнута!")
    elif ds <= 0: st.error("При текущих тратах копить не получается — сократи расходы.")
    else:
        n = int(left / ds) + 1
        st.caption(f"Осталось {R(left)} · при текущем темпе цель через {n} дн. ({(today + dt.timedelta(n)):%d.%m.%Y})")
    m1 = today.replace(day=1); sp = s(E, m1, today); pl = cfg["income"] * cfg["rate"] / 100
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Откладываю {cfg['rate']}%", R(pl)); c2.metric("Потрачено в месяце", R(sp), f"лимит {R(cfg['cap'])}", delta_color="off")
    c3.metric("Кешбек → накопления", R(s(C, m1, today)))
    st.metric("Остаток после трат (тоже в копилку)", R(cfg["income"] - pl - sp))
    td = s(E, today, today)
    st.metric("Сегодня", R(td), f"{td - lim:+,.0f} ₽ к дневному лимиту {R(lim)}".replace(",", " "), delta_color="inverse")
    for kind, t in motivate()[:4]: (st.warning if kind == "w" else st.info)(t)
    if sec("anthropic_key") and st.button("🤖 Разбор от Claude"):
        top = E[E.d >= today - dt.timedelta(30)].groupby("c").a.sum().sort_values(ascending=False).head(12).round().to_dict()
        p = (f"Я коплю 1 000 000 ₽, доход {cfg['income']}/мес, откладываю {cfg['rate']}% + остаток, кешбеки идут в накопления. "
             f"Накоплено {prog:.0f}, траты за 30 дней по категориям: {top}. Дай короткий разбор (до 150 слов): где лишнее, что сократить, как ускорить цель. Мотивируй.")
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=60,
                          headers={"x-api-key": sec("anthropic_key"), "anthropic-version": "2023-06-01"},
                          json={"model": "claude-sonnet-5-5", "max_tokens": 700, "messages": [{"role": "user", "content": p}]})
        st.info(r.json()["content"][0]["text"] if r.ok else "Ошибка API: " + r.text[:200])
    st.subheader("Внести")
    cats = [c for g in D["cats"].values() for c in [g]]  # порядок групп
    order = sorted(D["cats"], key=lambda c: (list(dict.fromkeys(D["cats"].values())).index(D["cats"][c]), c))
    with st.form("add", clear_on_submit=True):
        ty = st.radio("Тип", ["Трата", "Кешбек (в накопления)"], horizontal=True)
        a = st.number_input("Сумма, ₽", min_value=0.0, step=100.0)
        dd_ = st.date_input("Дата", today)
        c = st.selectbox("Категория (для трат)", order, format_func=lambda x: f"{D['cats'][x]} · {x}")
        n = st.text_input("Комментарий")
        if st.form_submit_button("Добавить", type="primary") and a > 0:
            cb = ty.startswith("Кешбек")
            D["exp"].append({"id": int(dt.datetime.now().timestamp() * 1000), "d": str(dd_), "c": "Кешбек" if cb else c, "a": a, "n": n, **({"t": "cb"} if cb else {})})
            D["exp"].sort(key=lambda e: (e["d"], e["id"])); commit()
    st.subheader("Последние записи")
    for e in D["exp"][-8:][::-1]:
        x, y = st.columns([5, 1])
        x.write(f"{e['d'][5:]} · {'🎁 Кешбек' if e.get('t') == 'cb' else e['c']} · **{'+' if e.get('t') == 'cb' else ''}{R(e['a'])}** {e.get('n') or ''}")
        if y.button("✕", key=f"x{e['id']}"):
            D["exp"].remove(e); commit()

with t2:
    def delta(a, b): return f"{a - b:+,.0f} ₽".replace(",", " ")
    w = today - dt.timedelta(today.weekday()); pw0 = w - dt.timedelta(7); k = dt.timedelta((today - w).days)
    pm = (today.replace(day=1) - day).replace(day=1); pme = pm.replace(day=min(today.day, calendar.monthrange(pm.year, pm.month)[1]))
    cmp_ = [("Сегодня к вчера", s(E, today, today), s(E, today - day, today - day)),
            ("Неделя к прошлой (на тот же день)", s(E, w, today), s(E, pw0, pw0 + k)),
            ("Месяц к прошлому (на то же число)", s(E, today.replace(day=1), today), s(E, pm, pme))]
    for col, (l, a, b) in zip(st.columns(3), cmp_): col.metric(l, R(a), delta(a, b), delta_color="inverse")
    days = [today - dt.timedelta(i) for i in range(13, -1, -1)]
    dd = pd.DataFrame({"d": days, "spent": [s(E, x, x) for x in days]}); dd["over"] = dd.spent > lim
    st.caption(f"Последние 14 дней (красный — выше дневного лимита {R(lim)})")
    st.altair_chart(alt.Chart(dd).mark_bar().encode(x=alt.X("d:T", title=None), y=alt.Y("spent:Q", title=None),
                    color=alt.Color("over:N", scale=alt.Scale(domain=[False, True], range=["#0f9d6b", "#d64545"]), legend=None))
                    + alt.Chart(pd.DataFrame({"y": [lim]})).mark_rule(strokeDash=[4, 4]).encode(y="y:Q"), width="stretch")
    st.subheader("Расходы по типам")
    p1, p2 = st.columns(2); per = p1.radio("Период", ["Неделя", "Месяц"], horizontal=True); mode = p2.radio("Разрез", ["Группы", "Категории"], horizontal=True)
    (a1, b1, b2) = (w, pw0, pw0 + k) if per == "Неделя" else (today.replace(day=1), pm, pme)
    key = "g" if mode == "Группы" else "c"
    cur = E[(E.d >= a1) & (E.d <= today)].groupby(key).a.sum(); prev = E[(E.d >= b1) & (E.d <= b2)].groupby(key).a.sum()
    T = pd.DataFrame({"Сейчас": cur, "Прошлый период": prev}).fillna(0); T["Δ"] = T["Сейчас"] - T["Прошлый период"]
    st.dataframe(T.sort_values("Сейчас", ascending=False).round(0), width="stretch")
    st.subheader("По месяцам")
    cm = today.strftime("%Y-%m"); rows = []
    for mth in sorted(set(F.m) | {cm})[-12:]:
        sp_, cb_ = E[E.m == mth].a.sum() if len(E) else 0, C[C.m == mth].a.sum() if len(C) else 0
        inc = cfg["income"] * (today.day / calendar.monthrange(today.year, today.month)[1] if mth == cm else 1)
        rows.append({"Месяц": mth, "Траты": round(sp_), "Кешбек": round(cb_), "Накоплено": round(inc - sp_ + cb_), "% дохода": round((inc - sp_ + cb_) / inc * 100)})
    M = pd.DataFrame(rows); L = M.melt("Месяц", ["Траты", "Накоплено"], "k", "v")
    st.altair_chart(alt.Chart(L).mark_bar().encode(x="Месяц:N", y=alt.Y("v:Q", title=None), xOffset="k:N",
                    color=alt.Color("k:N", scale=alt.Scale(domain=["Траты", "Накоплено"], range=["#d64545", "#0f9d6b"]), title=None)), width="stretch")
    st.dataframe(M.iloc[::-1], width="stretch", hide_index=True)
    st.caption("Накоплено = доход − траты + кешбек. Доход берётся из настроек, текущий месяц — пропорционально дням.")

with t3:
    st.caption("Меняй группу у категории, добавляй новые строки (внизу таблицы), удаляй лишние. Группа — любой текст.")
    ed = st.data_editor(pd.DataFrame({"Категория": list(D["cats"]), "Группа": list(D["cats"].values())}), num_rows="dynamic", width="stretch", hide_index=True)
    if st.button("Сохранить группы", type="primary"):
        D["cats"] = {r["Категория"].strip(): (r["Группа"] or "Прочее").strip() for _, r in ed.dropna(subset=["Категория"]).iterrows() if str(r["Категория"]).strip()}
        commit()

with t4:
    cfg["goal"] = st.number_input("Цель, ₽", value=float(cfg["goal"]), step=10000.0)
    cfg["start"] = st.number_input("Уже накоплено, ₽", value=float(cfg["start"]), step=1000.0)
    cfg["income"] = st.number_input("Доход в месяц, ₽", value=float(cfg["income"]), step=1000.0)
    cfg["rate"] = st.number_input("Откладывать, % дохода", value=float(cfg["rate"]), step=1.0)
    cfg["cap"] = st.number_input("Лимит трат в месяц, ₽", value=float(cfg["cap"]), step=1000.0)
    cfg["frm"] = str(st.date_input("Считать накопления с даты", dt.date.fromisoformat(cfg["frm"])))
    if st.button("Сохранить настройки", type="primary"): commit()
    st.divider(); st.subheader("Импорт из Excel (лист «Расходы»)")
    up = st.file_uploader("Файл .xlsx", type="xlsx")
    if up and st.button("Импортировать"):
        x = pd.read_excel(up, sheet_name="Расходы", header=None); x = x.iloc[x.index[x[0] == "Дата и время"][0] + 1:]
        seen = {(e["d"], e["c"], e["a"], e.get("n", "")) for e in D["exp"]}; n_ = 0
        for _, r in x.iterrows():
            d_, c_, a_ = pd.to_datetime(r[0], errors="coerce"), str(r[1]).strip(), pd.to_numeric(r[3], errors="coerce")
            nn = "" if pd.isna(r[8]) else str(r[8]).strip()
            if pd.isna(d_) or pd.isna(a_) or a_ <= 0 or c_ in ("Накопления", "nan") or (str(d_.date()), c_, float(a_), nn) in seen: continue
            D["cats"].setdefault(c_, "Прочее"); seen.add((str(d_.date()), c_, float(a_), nn)); n_ += 1
            D["exp"].append({"id": int(d_.timestamp() * 1000) + n_, "d": str(d_.date()), "c": c_, "a": float(a_), "n": nn})
        D["exp"].sort(key=lambda e: (e["d"], e["id"])); save(); st.success(f"Добавлено записей: {n_}"); st.rerun()
    st.divider(); st.subheader("Данные")
    st.download_button("Скачать копию (JSON)", json.dumps(D, ensure_ascii=False), "million-backup.json")
    st.caption("Хранилище: " + ("GitHub-репозиторий данных ☁️" if sec("github") else "локальный файл (на Streamlit Cloud сбрасывается — подключи GitHub, см. README)"))
    if sec("github") and st.button("Обновить из облака"):
        st.session_state.pop("D"); st.rerun()
