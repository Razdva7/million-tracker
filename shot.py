import json, base64, os, re, time, random, calendar, datetime as dt
import requests, pandas as pd, altair as alt, streamlit as st

st.set_page_config(page_title="Путь к миллиону", page_icon="💰")
st.html("""<style>.block-container{padding:.7rem .8rem 3rem;max-width:780px}h1,h2,h3{margin:0;padding:.25rem 0}
[data-testid=stMetricValue]{font-size:1.25rem}[data-testid=stMetricLabel]{font-size:.8rem}[data-testid=stHeader]{height:1.8rem}
div[data-testid=stVerticalBlock]{gap:.55rem}.stTabs [data-baseweb=tab]{padding:.4rem .5rem}</style>""")
GREEN, RED, BLUE, AMB = "#10b981", "#ef4444", "#3b82f6", "#f59e0b"
G0 = {"Обязательные": ["Ипотека", "Кварплата", "Связь", "Страховка", "Родителям долг за ремонт и квартиру", "Учеба в вузе"],
      "Еда": ["Продукты", "Обед на работе", "Кафе", "Кофе", "Алкоголь"], "Транспорт": ["Проезд на работу", "Транспорт", "Такси"],
      "Здоровье и уход": ["Здоровье", "Гигиена", "Стрижка"], "Семья": ["Важное для любимой", "Подарки"],
      "Досуг и покупки": ["Развлечения", "Досуг", "Отпуск", "Подписка", "Одежда", "Гаджеты и техника"], "Прочее": ["Дом", "Другое", "Образование"]}
MN = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]

def sec(k):
    try: return st.secrets[k]
    except Exception: return None

pw = sec("password")
if pw and not st.session_state.get("ok"):
    with st.form("login"):
        p = st.text_input("Пароль", type="password")
        if st.form_submit_button("Войти", type="primary"):
            if p.strip() == str(pw).strip(): st.session_state.ok = True; st.rerun()
            else: st.error("Неверный пароль")
    st.stop()

# ================= хранилище: ТОЛЬКО Яндекс.Диск (папка приложения) =================
LOCAL = os.environ.get("LOCAL_DEV"); YB = "https://cloud-api.yandex.net/v1/disk"
def ytok():
    g = sec("github"); return sec("yandex_token") or (g.get("yandex_token") if g else None)   # токен мог попасть внутрь блока [github]
def _h(): return {"Authorization": "OAuth " + str(ytok())}
def sget(p):
    if LOCAL:
        f = os.path.join(LOCAL, p); return json.load(open(f, encoding="utf-8")) if os.path.exists(f) else None
    r = requests.get(YB + "/resources/download", params={"path": "app:/" + p}, headers=_h(), timeout=20)
    if r.status_code == 404: return None
    r.raise_for_status(); x = requests.get(r.json()["href"], timeout=30); x.raise_for_status(); return x.json()
def sput(p, o):
    b = json.dumps(o, ensure_ascii=False).encode()
    if LOCAL:
        f = os.path.join(LOCAL, p); os.makedirs(os.path.dirname(f), exist_ok=True); open(f, "wb").write(b); return
    if not st.session_state.get("mk"):
        requests.put(YB + "/resources", params={"path": "app:/backups"}, headers=_h(), timeout=20); st.session_state.mk = 1
    r = requests.get(YB + "/resources/upload", params={"path": "app:/" + p, "overwrite": "true"}, headers=_h(), timeout=20); r.raise_for_status()
    requests.put(r.json()["href"], data=b, timeout=60).raise_for_status()
def slist():
    if LOCAL:
        d = os.path.join(LOCAL, "backups"); return sorted(os.listdir(d), reverse=True) if os.path.exists(d) else []
    r = requests.get(YB + "/resources", params={"path": "app:/backups", "limit": 1000, "sort": "-name"}, headers=_h(), timeout=20)
    return [i["name"] for i in r.json()["_embedded"]["items"]] if r.ok else []

def uid(): return int(time.time() * 1000) * 10 + random.randint(0, 9)
def default():
    return {"v": 2, "rev": 0, "cfg": {}, "cats": {c: g for g, l in G0.items() for c in l}, "exp": []}
def migrate(d):
    d = dict(d); d.setdefault("cfg", {}); c = d["cfg"]
    c.setdefault("goal", 1000000); c.setdefault("income", 149600); c.setdefault("cap", 90000)
    c.setdefault("pct", c.get("rate", 25)); c.setdefault("srate", 0.0); c.setdefault("frm", str(dt.date.today()))
    c.setdefault("start", 0.0); c.setdefault("sdate", c["frm"])
    for k, v in (("cats", {}), ("bud", {}), ("rec", []), ("exp", []), ("sav", []), ("inc", {}), ("trash", []), ("rev", 0)): d.setdefault(k, v)
    d["v"] = 2; return d
def merge(m, r):
    out = dict(m); r = migrate(r); tr = {t["id"] for t in m["trash"]} | {t["id"] for t in r["trash"]}
    for k in ("exp", "sav"):
        ids = {e["id"] for e in m[k]}
        out[k] = sorted(m[k] + [e for e in r[k] if e["id"] not in ids and e["id"] not in tr], key=lambda e: (e["d"], e["id"]))
    have = {t["id"] for t in m["trash"]}; out["trash"] = m["trash"] + [t for t in r["trash"] if t["id"] not in have]
    out["inc"] = {**r["inc"], **m["inc"]}; out["cats"] = {**r["cats"], **m["cats"]}; return out

if "D" not in st.session_state:
    if not (LOCAL or ytok()):
        try: ks = ", ".join(st.secrets.keys())
        except Exception: ks = "секретов нет"
        st.error("Не задан доступ к Яндекс.Диску: в Secrets нет `yandex_token`. Он должен стоять в самом верху, ДО строки `[github]`. Сейчас видны ключи: " + (ks or "—")); st.stop()
    try:
        d0 = sget("data.json")
        if d0 is None:
            nm = slist()
            if nm: d0 = sget("backups/" + nm[0]); st.session_state.note = "Основной файл не найден — загружена последняя резервная копия."
    except Exception as e:
        st.error(f"Не удалось прочитать Яндекс.Диск: {e}. Твои данные не тронуты."); st.button("Повторить"); st.stop()
    st.session_state.D = migrate(d0) if d0 else migrate(default()); st.session_state.base = (d0 or {}).get("rev", 0)
D = st.session_state.D; cfg = D["cfg"]
if st.session_state.get("note"): st.warning(st.session_state.pop("note"))

def save():
    try:
        rem = sget("data.json"); cur = st.session_state.D
        if rem and rem.get("rev", 0) != st.session_state.base:
            cur = st.session_state.D = merge(cur, rem); st.info("Данные были изменены на другом устройстве — объединил.")
        if rem: sput("backups/" + dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".json", rem)
        cur["rev"] = (rem or {}).get("rev", 0) + 1; sput("data.json", cur); st.session_state.base = cur["rev"]; return True
    except Exception as e:
        st.error(f"НЕ СОХРАНЕНО в Яндекс.Диск: {e}. Данные остались на экране — не закрывай страницу, повтори позже."); return False
def commit():
    if save(): st.rerun()
    st.stop()
def trash(kind, e):
    D[kind].remove(e); D["trash"].append({"id": e["id"], "k": kind, "e": e, "ts": dt.datetime.now().isoformat(timespec="seconds")}); D["trash"] = D["trash"][-500:]
def add(kind, **e):
    D[kind].append({"id": uid(), **e}); D[kind].sort(key=lambda x: (x["d"], x["id"]))

# ================= данные и расчёты =================
today = dt.date.today(); day = dt.timedelta(1); cm = today.strftime("%Y-%m")
R = lambda x: f"{x:,.0f} ₽".replace(",", " ")
def ml(m): return f"{MN[int(m[5:]) - 1]} {m[2:4]}"
def frame(rows, cols):
    f = pd.DataFrame(rows, columns=cols); f["d"] = pd.to_datetime(f["d"]).dt.date; f["a"] = pd.to_numeric(f["a"]); f["m"] = pd.to_datetime(f.d).dt.strftime("%Y-%m"); return f
F = frame(D["exp"], ["id", "d", "c", "a", "n", "t"]); F["t"] = F["t"].fillna("e"); F["g"] = F["c"].map(D["cats"]).fillna("Прочее")
S = frame(D["sav"], ["id", "d", "a", "k", "n"])
E, C, I = F[F.t == "e"], F[F.t == "cb"], F[F.t == "in"]
def s(df, a, b): return float(df[(df.d >= a) & (df.d <= b)].a.sum())

frm = min(dt.date.fromisoformat(cfg["frm"]), today); MC = {}; carry = 0.0; y, mo = frm.year, frm.month
while (y, mo) <= (today.year, today.month):
    m = f"{y}-{mo:02d}"; base = float(D["inc"].get(m, cfg["income"])); ex = float(I[I.m == m].a.sum()); inc = base + ex; pl = inc * cfg["pct"] / 100
    sp = float(E[E.m == m].a.sum()); p25 = float(S[(S.m == m) & (S.k == "p25")].a.sum()); oth = float(S[(S.m == m) & S.k.isin(["dep", "rest"])].a.sum()); wd = float(S[(S.m == m) & (S.k == "wd")].a.sum())
    cash = carry + inc - sp - p25 - oth + wd; need = max(0.0, pl - p25)
    MC[m] = dict(base=base, ex=ex, inc=inc, pl=pl, sp=sp, p25=p25, need=need, rest=cash - need, cin=carry); carry = cash
    mo += 1
    if mo > 12: y, mo = y + 1, 1
mc = MC[cm]

def engine(upto):
    fl = [(dt.date.fromisoformat(cfg["sdate"]), float(cfg["start"]))] + [(r.d, -r.a if r.k == "wd" else r.a) for r in S.itertuples()] + [(r.d, r.a) for r in C.itertuples()]
    fl = sorted(x for x in fl if x[0] <= upto)
    if not fl: return 0.0, 0.0
    rr = cfg["srate"] / 100 / 365; bal = pr = 0.0; i = 0; d = fl[0][0]
    while d <= upto:
        bal *= 1 + rr
        while i < len(fl) and fl[i][0] == d: bal += fl[i][1]; pr += fl[i][1]; i += 1
        d += day
    return bal, pr
bal, princ = engine(today); intr = bal - princ; rr = cfg["srate"] / 100 / 365; y12 = bal * ((1 + rr) ** 365 - 1)
first = F.d.min() if len(F) else today; win = min(30, (today - first).days + 1); w0 = today - dt.timedelta(win - 1)
spd = s(E, w0, today) / win if win >= 7 else cfg["cap"] / 30
m_add = max(0.0, mc["base"] - spd * 30.4) + s(C, w0, today) / win * 30.4; gain = max(m_add / 30.4, 1); lim = cfg["cap"] / 30
b_, n_mo = bal, 0
while b_ < cfg["goal"] and n_mo < 240 and (m_add > 0 or rr > 0): b_ = b_ * (1 + rr) ** 30.4 + m_add; n_mo += 1

def motivate():
    m = []; td, yd = s(E, today, today), s(E, today - day, today - day)
    if td > lim: m.append(("w", f"Сегодня на {R(td - lim)} больше лимита — это примерно {(td - lim) / gain:.1f} дн. задержки цели."))
    elif td > 0: m.append(("i", f"Сегодня в рамках лимита, запас {R(lim - td)} 💪"))
    else: m.append(("i", "Пока нет трат за сегодня. Не забудь внести расходы вечером."))
    w = today - dt.timedelta(today.weekday()); pw0 = w - dt.timedelta(7); k = dt.timedelta((today - w).days); diff = s(E, w, today) - s(E, pw0, pw0 + k)
    if s(E, pw0, w - day) > 0: m.append(("w", f"За неделю тратишь на {R(diff)} больше, чем в прошлую.") if diff > 0 else ("i", f"Неделя лучше прошлой на {R(-diff)} 👍"))
    a = E[(E.d >= w) & (E.g != "Обязательные")].groupby("c").a.sum(); b = E[(E.d >= pw0) & (E.d <= pw0 + k)].groupby("c").a.sum(); dd = a.sub(b, fill_value=0)
    if len(dd) and dd.max() > 500: m.append(("w", f"Сильнее всего выросла «{dd.idxmax()}» (+{R(dd.max())}) — это {dd.max() / gain:.1f} дн. цели."))
    return m

st.markdown("### 💰 Путь к миллиону")
tm, tv, ta, ts, th, tg, tx = st.tabs(["🏠 Главная", "➕ Внести", "📊 Аналитика", "💰 Накопления", "📜 История", "🗂 Группы", "⚙️ Ещё"])

# ================= Главная =================
with tm:
    st.metric("Накоплено (реально отложено)", R(bal), f"{bal / cfg['goal'] * 100:.1f}% от {R(cfg['goal'])}", delta_color="off")
    st.progress(max(0.0, min(1.0, bal / cfg["goal"])))
    sub = f"Вложено {R(princ)} · проценты {R(intr)} · ставка {cfg['srate']:g}% · ещё ~{R(y12)} за год"
    if bal >= cfg["goal"]: st.success("🎉 Цель достигнута!")
    elif n_mo >= 240 or (m_add <= 0 and rr == 0): sub += " · при текущем темпе цель недостижима"
    else: sub += f" · при таком темпе цель через {n_mo} мес. ({(today + dt.timedelta(n_mo * 30.4)):%m.%Y})"
    st.caption(sub)
    st.markdown(f"**{ml(cm)}** · доход {R(mc['inc'])} · потрачено {R(mc['sp'])} из лимита {R(cfg['cap'])}")
    c1, c2 = st.columns(2)
    c1.metric(f"Отложить {cfg['pct']:g}% дохода", R(mc["need"]), "уже отложено" if mc["need"] == 0 else f"всего {R(mc['pl'])}", delta_color="off")
    if mc["need"] > 0 and c1.button("Отложить в накопления", key="p25"): add("sav", d=str(today), a=round(mc["need"], 2), k="p25", n=f"{cfg['pct']:g}% за {ml(cm)}"); commit()
    c2.metric("Остаток после трат", R(mc["rest"]), f"перенос с прошлого {R(mc['cin'])}" if mc["cin"] else None, delta_color="off")
    if mc["rest"] > 0 and c2.button("Положить остаток", key="rest"): add("sav", d=str(today), a=round(mc["rest"], 2), k="rest", n=f"остаток {ml(cm)}"); commit()
    if (calendar.monthrange(today.year, today.month)[1] - today.day) < 3 and mc["rest"] > 0: st.info("Конец месяца — положи остаток в накопления. Если не положишь, он перейдёт на следующий месяц.")
    td = s(E, today, today); st.metric("Сегодня", R(td), f"{td - lim:+,.0f} ₽ к лимиту {R(lim)}".replace(",", " "), delta_color="inverse")
    for kind, t in motivate(): (st.warning if kind == "w" else st.info)(t)
    if D["bud"]:
        gm = E[E.m == cm].groupby("g").a.sum()
        for g_, l_ in D["bud"].items(): u = float(gm.get(g_, 0)); st.progress(min(1.0, u / l_), text=f"{g_}: {R(u)} из {R(l_)}" + (" ⚠️" if u > l_ else ""))
    if sec("anthropic_key") and st.button("🤖 Разбор от Claude"):
        top = E[E.d >= today - dt.timedelta(30)].groupby("c").a.sum().sort_values(ascending=False).head(12).round().to_dict()
        p = f"Коплю 1 000 000 ₽, доход {mc['inc']:.0f}/мес, откладываю {cfg['pct']}% + остаток. Накоплено {bal:.0f}, траты за 30 дней: {top}. Короткий разбор (до 150 слов): где лишнее, что сократить, как ускорить цель."
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=60, headers={"x-api-key": sec("anthropic_key"), "anthropic-version": "2023-06-01"},
                          json={"model": "claude-sonnet-5-5", "max_tokens": 700, "messages": [{"role": "user", "content": p}]})
        st.info(r.json()["content"][0]["text"] if r.ok else "Ошибка API: " + r.text[:200])
    st.markdown("**Последние записи**")
    for e in D["exp"][-6:][::-1]:
        x, y_ = st.columns([6, 1]); x.write(f"{e['d'][5:]} · {'🎁 Кешбек' if e.get('t') == 'cb' else e['c']} · **{'+' if e.get('t') in ('cb', 'in') else ''}{R(e['a'])}** {e.get('n') or ''}")
        if y_.button("✕", key=f"x{e['id']}"): trash("exp", e); commit()

# ================= Внести =================
with tv:
    kind = st.radio("Что вносим", ["Трата", "Кешбек", "Доп. доход", "Доход месяца", "В накопления", "Из накоплений", "Скриншот"], horizontal=True, label_visibility="collapsed")
    order = sorted(D["cats"], key=lambda c: (list(dict.fromkeys(D["cats"].values())).index(D["cats"][c]), c))
    if kind == "Трата":
        q = E[E.d >= today - dt.timedelta(90)].groupby(["c", "a"]).size().reset_index(name="k").query("k >= 2").sort_values("k", ascending=False).head(6)
        if len(q):
            qc = st.columns(3)
            for i_, (_, r_) in enumerate(q.iterrows()):
                if qc[i_ % 3].button(f"{r_['c']} · {r_['a']:.0f}", key=f"q{i_}"): add("exp", d=str(today), c=r_["c"], a=float(r_["a"]), n=""); commit()
    if kind in ("Трата", "Кешбек", "Доп. доход", "В накопления", "Из накоплений"):
        with st.form("add", clear_on_submit=True):
            a = st.number_input("Сумма, ₽", min_value=0.0, step=100.0); d_ = st.date_input("Дата", today)
            c = st.selectbox("Категория", order, format_func=lambda x: f"{D['cats'][x]} · {x}") if kind == "Трата" else None
            n = st.text_input("Комментарий" if kind != "Доп. доход" else "Источник (подработка, возврат…)")
            if st.form_submit_button("Добавить", type="primary") and a > 0:
                if kind == "Трата": add("exp", d=str(d_), c=c, a=a, n=n)
                elif kind == "Кешбек": add("exp", d=str(d_), c="Кешбек", a=a, n=n, t="cb")
                elif kind == "Доп. доход": add("exp", d=str(d_), c="Доп. доход", a=a, n=n, t="in")
                else: add("sav", d=str(d_), a=a, k="dep" if kind == "В накопления" else "wd", n=n)
                commit()
        if kind == "Кешбек": st.caption("Кешбек сразу попадает в накопления.")
        if kind == "Из накоплений": st.caption("Снятие уменьшает накопления и добавляет эту сумму в свободные деньги месяца.")
    if kind == "Доход месяца":
        ms_ = sorted(set(list(MC) + list(D["inc"])), reverse=True); mm = st.selectbox("Месяц", ms_, format_func=ml)
        v = st.number_input("Основной доход за этот месяц, ₽", value=float(D["inc"].get(mm, cfg["income"])), step=1000.0, key="vi" + mm)
        c1, c2 = st.columns(2)
        if c1.button("Сохранить доход месяца", type="primary"): D["inc"][mm] = v; commit()
        if mm in D["inc"] and c2.button("Сбросить к стандартному"): del D["inc"][mm]; commit()
        st.caption(f"Стандартный доход: {R(cfg['income'])}. Доп. доходы вносятся отдельно и прибавляются.")
    if kind == "Скриншот":
        import shot
        up = st.file_uploader("Скриншот списка трат — считаются тратами за выбранный день", type=["png", "jpg", "jpeg"]); sd = st.date_input("Дата трат", today, key="sd")
        if up:
            st.image(up, width=240)
            if st.button("Распознать", type="primary"):
                pb = st.progress(0.0, text="Загружаю модель… при первом запуске 1–2 минуты")
                try:
                    st.session_state.shot_txt = shot.read_image(up.getvalue(), sec("hf_model") or shot.MODEL, sec("hf_token"), pb)
                    st.session_state.shot_rows = shot.parse(st.session_state.shot_txt, D["cats"], D["exp"]); pb.empty()
                except Exception as e: pb.empty(); st.error(f"Не удалось распознать: {e}")
        if "shot_txt" in st.session_state:
            with st.expander("Распознанный текст (можно поправить)"):
                st.text_area("Текст", key="shot_txt", height=140, label_visibility="collapsed")
                if st.button("Разобрать текст заново"): st.session_state.shot_rows = shot.parse(st.session_state.shot_txt, D["cats"], D["exp"]); st.rerun()
        rows = st.session_state.get("shot_rows")
        if rows is not None:
            lab = {c: f"{D['cats'][c]} · {c}" for c in order}; seen = {(e["d"], e["c"], e["a"]) for e in D["exp"]}
            T = pd.DataFrame([{"Добавить": (str(sd), r_["c"], r_["a"]) not in seen, "Описание": r_["n"], "Сумма": r_["a"], "Категория": lab.get(r_["c"], lab.get("Другое", next(iter(lab.values()), "")))} for r_ in rows], columns=["Добавить", "Описание", "Сумма", "Категория"])
            if not len(T): st.warning("Трат не найдено. Поправь распознанный текст выше или добавь строки в таблицу вручную.")
            st.caption("Проверь список: поправь описание, сумму и категорию, лишнее удали. Новые строки — внизу таблицы. Галочка снята у возможных дублей.")
            ed = st.data_editor(T, num_rows="dynamic", hide_index=True, width="stretch", key="shotT", column_config={"Добавить": st.column_config.CheckboxColumn("✓"),
                "Сумма": st.column_config.NumberColumn("Сумма", min_value=0.0), "Категория": st.column_config.SelectboxColumn("Группа · категория", options=list(lab.values()))})
            if st.button("Добавить траты", type="primary"):
                n_ = 0
                for _, r_ in ed.iterrows():
                    if (pd.isna(r_["Добавить"]) or r_["Добавить"]) and pd.notna(r_["Сумма"]) and r_["Сумма"] > 0:
                        cat = str(r_["Категория"]).split(" · ", 1)[-1]; add("exp", d=str(sd), c=cat if cat in D["cats"] else "Другое", a=float(r_["Сумма"]), n="" if pd.isna(r_["Описание"]) else str(r_["Описание"])); n_ += 1
                st.session_state.pop("shot_rows", None); st.session_state.pop("shot_txt", None)
                if n_: commit()
                st.rerun()

# ================= Аналитика =================
with ta:
    ms = sorted(set(E.m) | {cm}, reverse=True); sel = st.selectbox("Месяц", ms, format_func=ml, label_visibility="collapsed")
    yy, mm_ = int(sel[:4]), int(sel[5:]); nd = calendar.monthrange(yy, mm_)[1]; st_ = dt.date(yy, mm_, 1); en = min(dt.date(yy, mm_, nd), today); el = (en - st_).days + 1
    pm = (st_ - day).strftime("%Y-%m"); Em, Ep = E[E.m == sel], E[E.m == pm]; sp, psp = float(Em.a.sum()), float(Ep.a.sum())
    inc = MC[sel]["inc"] if sel in MC else cfg["income"]; proj = sp / el * nd if sel == cm else sp
    k1, k2 = st.columns(2); k1.metric("Потрачено", R(sp), f"{sp - psp:+,.0f} ₽ к {ml(pm)}".replace(",", " "), delta_color="inverse"); k2.metric("В день", R(sp / el))
    k3, k4 = st.columns(2); k3.metric("Прогноз месяца" if sel == cm else "Итог месяца", R(proj), f"{proj - cfg['cap']:+,.0f} ₽ к лимиту".replace(",", " "), delta_color="inverse"); k4.metric("Доля дохода", f"{sp / inc * 100:.0f}%" if inc else "—", f"доход {R(inc)}", delta_color="off")
    dd = pd.DataFrame({"День": range(1, nd + 1)}); dd["Траты"] = [float(Em[Em.d == dt.date(yy, mm_, i)].a.sum()) for i in dd["День"]]; dd["Накопительно"] = dd["Траты"].cumsum(); dd["Лимит"] = [cfg["cap"] / nd * i for i in dd["День"]]
    if sel == cm: dd.loc[dd["День"] > today.day, "Накопительно"] = None
    st.caption("Траты по дням (красный — выше дневного лимита)")
    st.altair_chart(alt.Chart(dd).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(x=alt.X("День:O", axis=alt.Axis(labelAngle=0, values=list(range(1, nd + 1, 3)))), y=alt.Y("Траты:Q", title=None),
        color=alt.condition(alt.datum["Траты"] > lim, alt.value(RED), alt.value(GREEN))).properties(height=170), width="stretch")
    st.caption("Нарастающим итогом против плана по лимиту")
    lg = dd.melt("День", ["Накопительно", "Лимит"], "k", "v")
    st.altair_chart(alt.Chart(lg).mark_line(strokeWidth=3).encode(x=alt.X("День:Q", title=None), y=alt.Y("v:Q", title=None), color=alt.Color("k:N", scale=alt.Scale(domain=["Накопительно", "Лимит"], range=[BLUE, "#9ca3af"]), title=None),
        strokeDash=alt.condition(alt.datum.k == "Лимит", alt.value([5, 4]), alt.value([0]))).properties(height=170), width="stretch")
    pie = Em.groupby("g").a.sum().reset_index()
    if len(pie):
        st.caption("Структура расходов по группам")
        st.altair_chart(alt.Chart(pie).mark_arc(innerRadius=60).encode(theta="a:Q", color=alt.Color("g:N", title=None, scale=alt.Scale(scheme="tableau10")), tooltip=["g", "a"]).properties(height=220), width="stretch")
        cat = pd.concat([Em.groupby("c").a.sum().rename("Этот месяц"), Ep.groupby("c").a.sum().rename("Прошлый")], axis=1).fillna(0).sort_values("Этот месяц", ascending=False).head(10).reset_index().rename(columns={"index": "c"})
        st.caption("Топ-10 категорий: этот и прошлый месяц")
        st.altair_chart(alt.Chart(cat.melt("c", ["Этот месяц", "Прошлый"], "p", "v")).mark_bar().encode(y=alt.Y("c:N", sort=list(cat["c"]), title=None), x=alt.X("v:Q", title=None), yOffset="p:N",
            color=alt.Color("p:N", scale=alt.Scale(domain=["Этот месяц", "Прошлый"], range=[GREEN, "#cbd5e1"]), title=None)).properties(height=max(200, 34 * len(cat))), width="stretch")
        st.caption("Крупнейшие траты месяца"); st.dataframe(Em.nlargest(10, "a")[["d", "c", "a", "n"]].rename(columns={"d": "Дата", "c": "Категория", "a": "Сумма", "n": "Комментарий"}), hide_index=True, width="stretch")
    rows = []
    for m_ in sorted(set(F.m) | set(MC))[-12:]:
        sp_ = float(E[E.m == m_].a.sum()); inc_ = MC[m_]["inc"] if m_ in MC else float(D["inc"].get(m_, cfg["income"])) + float(I[I.m == m_].a.sum())
        sv = float(S[(S.m == m_) & (S.k != "wd")].a.sum()) + float(C[C.m == m_].a.sum()) - float(S[(S.m == m_) & (S.k == "wd")].a.sum()); rows.append({"Месяц": ml(m_), "Доход": inc_, "Траты": sp_, "Отложено": sv, "% отложено": round(sv / inc_ * 100) if inc_ else 0})
    M = pd.DataFrame(rows); st.caption("Динамика по месяцам")
    st.altair_chart(alt.Chart(M.melt("Месяц", ["Доход", "Траты", "Отложено"], "k", "v")).mark_bar().encode(x=alt.X("Месяц:N", sort=list(M["Месяц"]), title=None), y=alt.Y("v:Q", title=None), xOffset="k:N",
        color=alt.Color("k:N", scale=alt.Scale(domain=["Доход", "Траты", "Отложено"], range=[BLUE, RED, GREEN]), title=None)).properties(height=220), width="stretch")
    st.dataframe(M.iloc[::-1].round(0), hide_index=True, width="stretch")

# ================= Накопления =================
with ts:
    st.metric("Накоплено", R(bal), f"проценты {R(intr)}", delta_color="off"); a1, a2 = st.columns(2); a1.metric("Вложено своих", R(princ)); a2.metric("Доход за год при текущей сумме", R(y12), f"≈ {R(y12 / 12)} в месяц", delta_color="off")
    with st.expander("Ставка и стартовая сумма", expanded=False):
        cfg["srate"] = st.number_input("Ставка по накоплениям, % годовых", value=float(cfg["srate"]), step=0.5, min_value=0.0)
        cfg["start"] = st.number_input("Сумма накоплений на дату старта, ₽", value=float(cfg["start"]), step=1000.0)
        cfg["sdate"] = str(st.date_input("Дата, с которой считать проценты", dt.date.fromisoformat(cfg["sdate"])))
        if st.button("Сохранить", key="ssv", type="primary"): commit()
        st.caption("Проценты начисляются ежедневно с капитализацией на фактическую сумму; кешбек входит в накопления.")
    me = sorted(set(list(MC)))[-12:]; gr = pd.DataFrame({"Месяц": [ml(m_) for m_ in me], "Накоплено": [engine(min(today, dt.date(int(m_[:4]), int(m_[5:]), calendar.monthrange(int(m_[:4]), int(m_[5:]))[1])))[0] for m_ in me]})
    if len(gr) > 1: st.altair_chart(alt.Chart(gr).mark_area(line={"color": GREEN}, color=alt.Gradient(gradient="linear", stops=[alt.GradientStop(color=GREEN, offset=0), alt.GradientStop(color="white", offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x=alt.X("Месяц:N", sort=list(gr["Месяц"]), title=None), y=alt.Y("Накоплено:Q", title=None)).properties(height=180), width="stretch")
    st.markdown("**Операции**"); lab = {"dep": "Положил", "wd": "Снял", "p25": "Отложил %", "rest": "Остаток"}
    for e in D["sav"][-15:][::-1]:
        x, y_ = st.columns([6, 1]); x.write(f"{e['d'][5:]} · {lab.get(e['k'], e['k'])} · **{'−' if e['k'] == 'wd' else '+'}{R(e['a'])}** {e.get('n') or ''}")
        if y_.button("✕", key=f"sv{e['id']}"): trash("sav", e); commit()

# ================= История =================
with th:
    f1, f2 = st.columns(2); rng = f1.date_input("Период", (today.replace(day=1), today)); KT = {"Траты": "e", "Кешбеки": "cb", "Доп. доходы": "in"}
    kinds = f2.multiselect("Тип", list(KT), default=list(KT)); cs = st.multiselect("Категории", sorted(D["cats"])); q_ = st.text_input("Поиск по комментарию")
    H = F[F.t.isin([KT[k] for k in kinds])]
    if len(rng) == 2: H = H[(H.d >= rng[0]) & (H.d <= rng[1])]
    if cs: H = H[H.c.isin(cs)]
    if q_: H = H[H.n.fillna("").str.contains(q_, case=False)]
    H = H.sort_values(["d", "id"], ascending=False); st.caption(f"Найдено: {len(H)} · траты {R(H[H.t == 'e'].a.sum())}" + (" · показаны первые 300" if len(H) > 300 else ""))
    st.download_button("Скачать CSV", H[["d", "c", "a", "n", "t"]].to_csv(index=False).encode("utf-8-sig"), "expenses.csv")
    ed2 = st.data_editor(H.head(300)[["id", "d", "c", "a", "n"]].assign(Удалить=False).set_index("id"), hide_index=True, width="stretch", key="hist",
        column_config={"d": st.column_config.DateColumn("Дата"), "c": st.column_config.SelectboxColumn("Категория", options=sorted(D["cats"]) + ["Кешбек", "Доп. доход"]), "a": st.column_config.NumberColumn("Сумма", min_value=0.0), "n": st.column_config.TextColumn("Комментарий")})
    if st.button("Сохранить изменения", type="primary"):
        by = {e["id"]: e for e in D["exp"]}
        for i_, r_ in ed2.iterrows():
            e = by.get(int(i_))
            if e is None: continue
            if r_["Удалить"]: trash("exp", e)
            else: e.update(d=str(pd.to_datetime(r_["d"]).date()), c=r_["c"], a=float(r_["a"]), n="" if pd.isna(r_["n"]) else r_["n"])
        D["exp"].sort(key=lambda e: (e["d"], e["id"])); commit()
    st.caption("Удалённое попадает в корзину (вкладка «Ещё») — его можно вернуть.")

# ================= Группы =================
with tg:
    st.caption("Меняй группу у категории, добавляй строки внизу таблицы. Прежние настройки всегда можно вернуть из резервной копии (вкладка «Ещё»).")
    ed = st.data_editor(pd.DataFrame({"Категория": list(D["cats"]), "Группа": list(D["cats"].values())}), num_rows="dynamic", width="stretch", hide_index=True)
    if st.button("Сохранить группы", type="primary"):
        new = {str(r["Категория"]).strip(): str(r["Группа"] or "Прочее").strip() for _, r in ed.dropna(subset=["Категория"]).iterrows() if str(r["Категория"]).strip()}
        if not new: st.error("Список пуст — не сохраняю.")
        else: D["cats"] = new; commit()
    gl = list(dict.fromkeys(D["cats"].values())); st.markdown("**Бюджеты по группам (в месяц)**")
    be = st.data_editor(pd.DataFrame({"Группа": gl, "Лимит, ₽": [float(D["bud"].get(g_, 0)) for g_ in gl]}), disabled=["Группа"], hide_index=True, width="stretch", key="be")
    if st.button("Сохранить бюджеты"): D["bud"] = {r_["Группа"]: float(r_["Лимит, ₽"]) for _, r_ in be.iterrows() if r_["Лимит, ₽"] > 0}; commit()
    st.markdown("**Регулярные платежи** (сами добавляются в траты в нужный день)")
    rdf = pd.DataFrame(D["rec"], columns=["c", "a", "day", "n", "last"]); rdf["a"] = pd.to_numeric(rdf["a"]); rdf["day"] = pd.to_numeric(rdf["day"])
    re_ = st.data_editor(rdf, num_rows="dynamic", hide_index=True, width="stretch", key="re", column_config={"last": None, "c": st.column_config.SelectboxColumn("Категория", options=sorted(D["cats"]), required=True),
        "a": st.column_config.NumberColumn("Сумма", min_value=0.0), "day": st.column_config.NumberColumn("День месяца", min_value=1, max_value=31, step=1), "n": st.column_config.TextColumn("Комментарий")})
    if st.button("Сохранить регулярные"):
        out = []
        for _, r_ in re_.iterrows():
            if pd.isna(r_["c"]) or pd.isna(r_["a"]) or pd.isna(r_["day"]): continue
            last = r_["last"] if isinstance(r_["last"], str) else (today if int(r_["day"]) <= today.day else today.replace(day=1) - day).strftime("%Y-%m")
            out.append({"c": r_["c"], "a": float(r_["a"]), "day": int(r_["day"]), "n": "" if pd.isna(r_["n"]) else r_["n"], "last": last})
        D["rec"] = out; commit()

# ================= Ещё: настройки, резервные копии, восстановление =================
with tx:
    st.markdown("**Настройки**")
    cfg["goal"] = st.number_input("Цель, ₽", value=float(cfg["goal"]), step=10000.0); cfg["income"] = st.number_input("Стандартный доход в месяц, ₽", value=float(cfg["income"]), step=1000.0)
    cfg["pct"] = st.number_input("Откладывать, % дохода", value=float(cfg["pct"]), step=1.0); cfg["cap"] = st.number_input("Лимит трат в месяц, ₽", value=float(cfg["cap"]), step=1000.0)
    cfg["frm"] = str(st.date_input("Начало учёта остатков (месяц старта)", dt.date.fromisoformat(cfg["frm"])))
    if st.button("Сохранить настройки", type="primary"): commit()
    st.divider(); st.markdown("**🗑 Корзина**")
    if D["trash"]:
        if st.button("Вернуть всё удалённое"):
            for t in D["trash"]:
                if t["e"]["id"] not in {e["id"] for e in D[t["k"]]}: D[t["k"]].append(t["e"])
            D["trash"] = []
            for k in ("exp", "sav"): D[k].sort(key=lambda e: (e["d"], e["id"]))
            commit()
        for t in D["trash"][-10:][::-1]:
            x, y_ = st.columns([6, 1]); e = t["e"]; x.write(f"{e['d']} · {e.get('c') or e.get('k')} · {R(e['a'])} (удалено {t['ts'][:16]})")
            if y_.button("↩", key=f"rt{t['id']}"): D["trash"].remove(t); D[t["k"]].append(e); D[t["k"]].sort(key=lambda z: (z["d"], z["id"])); commit()
    else: st.caption("Корзина пуста.")
    st.divider(); st.markdown("**♻️ Резервные копии на Яндекс.Диске**"); st.caption("Копия создаётся автоматически при каждом сохранении (состояние ДО изменения).")
    try: names = slist()
    except Exception as e: names = []; st.error(f"Не удалось получить список: {e}")
    if names:
        pick = st.selectbox("Версия", names[:200], format_func=lambda n: f"{n[:4]}-{n[4:6]}-{n[6:8]} {n[9:11]}:{n[11:13]}:{n[13:15]}")
        if st.button("Показать, что в копии"): st.session_state.prev = migrate(sget("backups/" + pick))
        pv = st.session_state.get("prev")
        if pv:
            st.info(f"Трат/записей: {len(pv['exp'])} · накоплений-операций: {len(pv['sav'])} · категорий: {len(pv['cats'])} · групп: {len(set(pv['cats'].values()))}")
            b1, b2, b3 = st.columns(3)
            if b1.button("Восстановить всё"): st.session_state.D = D = pv; commit()
            if b2.button("Только группы и бюджеты"): D["cats"], D["bud"], D["rec"] = pv["cats"], pv["bud"], pv["rec"]; commit()
            if b3.button("Только траты и накопления"): D["exp"], D["sav"], D["inc"] = pv["exp"], pv["sav"], pv["inc"]; commit()
    else: st.caption("Копий пока нет.")
    c1, c2 = st.columns(2)
    if c1.button("🔄 Обновить с Яндекс.Диска"):
        try: r_ = sget("data.json")
        except Exception as e: r_ = None; st.error(f"Не удалось: {e}")
        if r_: st.session_state.D = migrate(r_); st.session_state.base = r_.get("rev", 0); st.rerun()
    c2.download_button("⬇️ Скачать полную копию", json.dumps(D, ensure_ascii=False), "million-backup.json")
    jf = st.file_uploader("Восстановить из файла копии (в т.ч. из старой версии)", type="json")
    if jf and st.button("Загрузить файл в приложение"): st.session_state.D = D = merge(D, json.load(jf)); commit()
    if sec("github"):
        st.divider(); st.markdown("**Импорт истории из старого хранилища GitHub** (разово)")
        g = sec("github"); hd = {"Authorization": "token " + g["token"]}
        try:
            cm_ = requests.get(f"https://api.github.com/repos/{g['repo']}/commits", params={"path": g.get("path", "data.json"), "per_page": 40}, headers=hd, timeout=20).json()
            ch = st.selectbox("Версия в истории Git", cm_, format_func=lambda c: c["commit"]["author"]["date"][:16].replace("T", " "))
            if st.button("Показать версию"):
                rj = requests.get(f"https://api.github.com/repos/{g['repo']}/contents/{g.get('path', 'data.json')}", params={"ref": ch["sha"]}, headers=hd, timeout=20).json()
                st.session_state.gv = migrate(json.loads(base64.b64decode(rj["content"]).decode()))
            if st.session_state.get("gv"):
                gv = st.session_state.gv; st.info(f"В версии записей: {len(gv['exp'])}, категорий: {len(gv['cats'])}")
                if st.button("Добавить эти данные к текущим"): st.session_state.D = D = merge(D, gv); commit()
        except Exception as e: st.caption(f"GitHub недоступен: {e}")
    st.divider(); st.markdown("**Импорт из Excel** (лист «Расходы»)"); up = st.file_uploader("Файл .xlsx", type="xlsx")
    if up and st.button("Импортировать"):
        x = pd.read_excel(up, sheet_name="Расходы", header=None); x = x.iloc[x.index[x[0] == "Дата и время"][0] + 1:]; seen = {(e["d"], e["c"], e["a"], e.get("n", "")) for e in D["exp"]}; n_ = 0
        for _, r in x.iterrows():
            d_, c_, a_ = pd.to_datetime(r[0], errors="coerce"), str(r[1]).strip(), pd.to_numeric(r[3], errors="coerce"); nn = "" if pd.isna(r[8]) else str(r[8]).strip()
            if pd.isna(d_) or pd.isna(a_) or a_ <= 0 or c_ in ("Накопления", "nan") or (str(d_.date()), c_, float(a_), nn) in seen: continue
            D["cats"].setdefault(c_, "Прочее"); seen.add((str(d_.date()), c_, float(a_), nn)); n_ += 1; add("exp", d=str(d_.date()), c=c_, a=float(a_), n=nn)
        st.success(f"Добавлено: {n_}"); commit()

# регулярные платежи — после отрисовки, чтобы не мешать данным
def apply_rec():
    ch = False
    for r in D["rec"]:
        y, m = map(int, r["last"].split("-"))
        while (y, m) < (today.year, today.month):
            m += 1
            if m > 12: y, m = y + 1, 1
            d_ = dt.date(y, m, min(int(r["day"]), calendar.monthrange(y, m)[1]))
            if d_ > today: break
            add("exp", d=str(d_), c=r["c"], a=float(r["a"]), n=("авто " + r["n"]).strip()); r["last"] = f"{y}-{m:02d}"; ch = True
    if ch: commit()
apply_rec()
