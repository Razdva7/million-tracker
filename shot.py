"""Распознавание скриншота трат лёгкой моделью Hugging Face + разбор в строки «описание / сумма / категория»."""
import re, io, base64
from collections import Counter
import streamlit as st

MODEL = "HuggingFaceTB/SmolVLM-256M-Instruct"   # ~256M параметров, работает на CPU; можно заменить секретом hf_model
PROMPT = "Transcribe all the text in this image exactly, line by line. Include every amount with its currency sign."

@st.cache_resource(show_spinner=False)
def load_vlm(name):
    import torch
    from transformers import AutoProcessor, AutoModelForVision2Seq
    return AutoProcessor.from_pretrained(name), AutoModelForVision2Seq.from_pretrained(name, torch_dtype=torch.bfloat16).eval()

def slices(img):
    w, h = img.size; step = int(w * 1.1)
    if h <= step * 1.3: return [img]
    out, y = [], 0
    while y < h and len(out) < 5:
        out.append(img.crop((0, y, w, min(h, y + step)))); y += step - int(w * 0.1)
    return out

def read_image(data, name=MODEL, token=None, progress=None):
    from PIL import Image
    img = Image.open(io.BytesIO(data)).convert("RGB"); parts = slices(img); lines = []
    if token:  # режим API: модель работает на серверах Hugging Face, локально ничего не грузится
        from huggingface_hub import InferenceClient
        cl = InferenceClient(model=name, token=token)
    else:
        import torch; proc, model = load_vlm(name)
    for i, p in enumerate(parts):
        if progress: progress.progress(i / len(parts), text=f"Читаю часть {i + 1} из {len(parts)}…")
        if token:
            b = io.BytesIO(); p.save(b, "PNG")
            r = cl.chat_completion(messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()}}, {"type": "text", "text": PROMPT}]}], max_tokens=500)
            txt = r.choices[0].message.content
        else:
            msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": PROMPT}]}]
            inp = proc(text=proc.apply_chat_template(msgs, add_generation_prompt=True), images=[p], return_tensors="pt")
            with torch.inference_mode(): out = model.generate(**inp, max_new_tokens=350, do_sample=False)
            txt = proc.batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0]
        for ln in txt.splitlines():
            ln = ln.strip()
            if ln and (not lines or lines[-1] != ln): lines.append(ln)
    if progress: progress.progress(1.0, text="Готово")
    return "\n".join(lines)

KW = {"Продукты": ["пятёрочка", "пятерочка", "магнит", "перекрёсток", "перекресток", "лента", "ашан", "дикси", "вкусвилл", "окей", "продукт", "супермаркет", "spar", "азбука вкуса", "верный"],
      "Кафе": ["кафе", "ресторан", "бургер", "kfc", "макдоналдс", "вкусно", "пицц", "суши", "додо", "столов", "шаурма", "бистро", "burger"],
      "Кофе": ["кофе", "coffee", "starbucks", "кофейн", "шоколадница"], "Такси": ["такси", "yandex go", "яндекс go", "uber", "ситимобил", "indrive", "ситидрайв"],
      "Транспорт": ["метро", "автобус", "трамвай", "парковк", "азс", "бензин", "лукойл", "роснефть", "газпромнефть", "тройка", "транспорт"],
      "Связь": ["мтс", "билайн", "мегафон", "теле2", "tele2", "связь", "ростелеком"], "Подписка": ["подписк", "netflix", "spotify", "плюс", "кинопоиск", "okko", "ivi", "youtube", "apple", "google"],
      "Здоровье": ["аптек", "клиник", "стоматолог", "врач", "анализ", "ригла", "здоров"], "Гигиена": ["рив гош", "летуаль", "золотое яблоко", "косметик", "гигиен"],
      "Одежда": ["одежд", "обувь", "спортмастер", "zara", "h&m", "лаймшоп"], "Алкоголь": ["винлаб", "красное", "бристоль", "алко", "пиво", "вино"],
      "Развлечения": ["кино", "театр", "концерт", "боулинг", "игр", "steam"], "Дом": ["леруа", "хоум", "икеа", "ikea", "обои", "сантехник", "хозтовар", "fix price"]}
SKIP = re.compile(r"итого|всего|баланс|остаток|доступно|кешбек|кэшбэк|cashback|сумма за|за день|за месяц|total|balance", re.I)
AMT = re.compile(r"(?<![\w.,])[-−–]?\s?(\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(₽|руб\.?|р\b\.?|rub)?(?![\w])", re.I)
NOISE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|\b\d{1,2}:\d{2}(?::\d{2})?\b")

def _num(x): return float(re.sub(r"[ \u00a0\u202f]", "", x).replace(",", "."))
MON = re.compile(r"январ|феврал|март|апрел|\bма[йя]\b|июн|июл|август|сентябр|октябр|ноябр|декабр|сегодня|вчера", re.I)
def _find(line, req):
    ms = [m for m in AMT.finditer(NOISE.sub(" ", line)) if 1 <= _num(m.group(1)) <= 5_000_000]
    cur = [m for m in ms if m.group(2)]
    if req or MON.search(line): ms = cur
    return (cur or ms[-1:] or [None])[-1]

def categorize(desc, cats, hist):
    t = desc.lower()
    for c in cats:
        if len(c) >= 4 and c.lower() in t: return c
    votes = Counter()
    for tok in re.findall(r"[a-zа-яё]{4,}", t): votes.update(hist.get(tok, {}))
    if votes: return votes.most_common(1)[0][0]
    for c, kws in KW.items():
        if c in cats and any(k in t for k in kws): return c
    return "Другое" if "Другое" in cats else next(iter(cats))

def parse(text, cats, exp):
    hist = {}
    for e in exp:
        if e.get("t") in (None, "e") and e.get("n") and not e["n"].startswith("авто") and e["c"] in cats:
            for tok in re.findall(r"[a-zа-яё]{4,}", e["n"].lower()): hist.setdefault(tok, Counter())[e["c"]] += 1
    rows, prev = [], None
    req = sum(1 for m in AMT.finditer(NOISE.sub(" ", text)) if m.group(2)) >= 2   # если в списке есть значки ₽ — числа без ₽ считаем не суммами
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or SKIP.search(ln): prev = None; continue
        m = _find(ln, req); desc = re.sub(r"[\s:|•·\-–—]+$|^[\s:|•·\-–—]+", "", AMT.sub(" ", NOISE.sub(" ", ln)) if m else ln).strip()
        has_letters = bool(re.search(r"[A-Za-zА-Яа-яЁё]{2,}", desc))
        if m and has_letters: rows.append((desc, _num(m.group(1)))); prev = None
        elif m and prev: rows.append((prev, _num(m.group(1)))); prev = None
        elif m: rows.append(("", _num(m.group(1))))
        else: prev = desc if has_letters else None
    return [{"n": d, "a": a, "c": categorize(d, cats, hist)} for d, a in rows]
