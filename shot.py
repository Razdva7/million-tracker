
"""Распознавание скриншотов расходов через Hugging Face SmolVLM."""

import re
import io
import base64
from collections import Counter

import streamlit as st

MODEL = "HuggingFaceTB/SmolVLM-256M-Instruct"

PROMPT = (
    "Transcribe all the text in this image exactly, line by line. "
    "Include every amount with its currency sign."
)


# ================= Загрузка модели =================

@st.cache_resource(show_spinner=False)
def load_vlm(name):
    import torch
    from transformers import AutoProcessor, AutoModelForImageTextToText

    processor = AutoProcessor.from_pretrained(name)

    model = AutoModelForImageTextToText.from_pretrained(
        name,
        torch_dtype=torch.float32
    ).eval()

    return processor, model


# ================= Разделение изображения =================

def slices(img):
    w, h = img.size
    step = int(w * 1.1)

    if h <= step * 1.3:
        return [img]

    out = []
    y = 0

    while y < h and len(out) < 5:
        out.append(
            img.crop((0, y, w, min(h, y + step)))
        )
        y += step - int(w * 0.1)

    return out


# ================= Распознавание изображения =================

def read_image(data, name=MODEL, token=None, progress=None):
    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    parts = slices(img)
    lines = []

    if token:
        from huggingface_hub import InferenceClient

        client = InferenceClient(
            model=name,
            token=token
        )
    else:
        import torch

        processor, model = load_vlm(name)

    for i, part in enumerate(parts):

        if progress:
            progress.progress(
                i / len(parts),
                text=f"Читаю часть {i + 1} из {len(parts)}…"
            )

        if token:
            buffer = io.BytesIO()
            part.save(buffer, "PNG")

            encoded = base64.b64encode(
                buffer.getvalue()
            ).decode()

            response = client.chat_completion(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64," + encoded
                                }
                            },
                            {
                                "type": "text",
                                "text": PROMPT
                            }
                        ]
                    }
                ],
                max_tokens=500
            )

            txt = response.choices[0].message.content

        else:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},
                        {"type": "text", "text": PROMPT}
                    ]
                }
            ]

            inputs = processor(
                text=processor.apply_chat_template(
                    messages,
                    add_generation_prompt=True
                ),
                images=[part],
                return_tensors="pt"
            )

            with torch.inference_mode():
                output = model.generate(
                    **inputs,
                    max_new_tokens=350,
                    do_sample=False
                )

            txt = processor.batch_decode(
                output[:, inputs["input_ids"].shape[1]:],
                skip_special_tokens=True
            )[0]

        for line in txt.splitlines():
            line = line.strip()

            if line and (not lines or lines[-1] != line):
                lines.append(line)

    if progress:
        progress.progress(1.0, text="Готово")

    return "\n".join(lines)


# ================= Категории расходов =================

KW = {
    "Продукты": [
        "пятёрочка", "пятерочка", "магнит", "перекрёсток",
        "перекресток", "лента", "ашан", "дикси",
        "вкусвилл", "окей", "продукт", "супермаркет",
        "spar", "азбука вкуса", "верный"
    ],

    "Кафе": [
        "кафе", "ресторан", "бургер", "kfc",
        "макдоналдс", "вкусно", "пицц", "суши",
        "додо", "столов", "шаурма", "бистро", "burger"
    ],

    "Кофе": [
        "кофе", "coffee", "starbucks",
        "кофейн", "шоколадница"
    ],

    "Такси": [
        "такси", "yandex go", "яндекс go",
        "uber", "ситимобил", "indrive", "ситидрайв"
    ],

    "Транспорт": [
        "метро", "автобус", "трамвай", "парковк",
        "азс", "бензин", "лукойл", "роснефть",
        "газпромнефть", "тройка", "транспорт"
    ],

    "Связь": [
        "мтс", "билайн", "мегафон",
        "теле2", "tele2", "связь", "ростелеком"
    ],

    "Подписка": [
        "подписк", "netflix", "spotify", "плюс",
        "кинопоиск", "okko", "ivi", "youtube",
        "apple", "google"
    ],

    "Здоровье": [
        "аптек", "клиник", "стоматолог",
        "врач", "анализ", "ригла", "здоров"
    ],

    "Гигиена": [
        "рив гош", "летуаль", "золотое яблоко",
        "косметик", "гигиен"
    ],

    "Одежда": [
        "одежд", "обувь", "спортмастер",
        "zara", "h&m", "лаймшоп"
    ],

    "Алкоголь": [
        "винлаб", "красное", "бристоль",
        "алко", "пиво", "вино"
    ],

    "Развлечения": [
        "кино", "театр", "концерт",
        "боулинг", "игр", "steam"
    ],

    "Дом": [
        "леруа", "хоум", "икеа", "ikea",
        "обои", "сантехник", "хозтовар", "fix price"
    ]
}


SKIP = re.compile(
    r"итого|всего|баланс|остаток|доступно|кешбек|"
    r"кэшбэк|cashback|сумма за|за день|за месяц|"
    r"total|balance",
    re.I
)

AMT = re.compile(
    r"(?<![\w.,])[-−–]?\s?"
    r"(\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?"
    r"|\d+(?:[.,]\d{1,2})?)"
    r"\s*(₽|руб\.?|р\b\.?|rub)?(?![\w])",
    re.I
)

NOISE = re.compile(
    r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|"
    r"\b\d{1,2}:\d{2}(?::\d{2})?\b"
)


def _num(x):
    return float(
        re.sub(r"[ \u00a0\u202f]", "", x).replace(",", ".")
    )


MON = re.compile(
    r"январ|феврал|март|апрел|\bма[йя]\b|июн|июл|"
    r"август|сентябр|октябр|ноябр|декабр|сегодня|вчера",
    re.I
)


def _find(line, req):
    matches = [
        m for m in AMT.finditer(NOISE.sub(" ", line))
        if 1 <= _num(m.group(1)) <= 5_000_000
    ]

    currency = [m for m in matches if m.group(2)]

    if req or MON.search(line):
        matches = currency

    return (currency or matches[-1:] or [None])[-1]


# ================= Автоматическая категоризация =================

def categorize(desc, cats, hist):
    text = desc.lower()

    for category in cats:
        if len(category) >= 4 and category.lower() in text:
            return category

    votes = Counter()

    for token in re.findall(r"[a-zа-яё]{4,}", text):
        votes.update(hist.get(token, {}))

    if votes:
        return votes.most_common(1)[0][0]

    for category, keywords in KW.items():
        if category in cats and any(
            keyword in text for keyword in keywords
        ):
            return category

    return "Другое" if "Другое" in cats else next(iter(cats))


# ================= Разбор текста на расходы =================

def parse(text, cats, exp):
    hist = {}

    for expense in exp:
        if (
            expense.get("t") in (None, "e")
            and expense.get("n")
            and not expense["n"].startswith("авто")
            and expense["c"] in cats
        ):
            for token in re.findall(
                r"[a-zа-яё]{4,}",
                expense["n"].lower()
            ):
                hist.setdefault(token, Counter())[
                    expense["c"]
                ] += 1

    rows = []
    prev = None

    req = sum(
        1 for m in AMT.finditer(NOISE.sub(" ", text))
        if m.group(2)
    ) >= 2

    for line in text.splitlines():
        line = line.strip()

        if not line or SKIP.search(line):
            prev = None
            continue

        match = _find(line, req)

        clean = NOISE.sub(" ", line)

        desc = re.sub(
            r"[\s:|•·\-–—]+$|^[\s:|•·\-–—]+",
            "",
            AMT.sub(" ", clean) if match else clean
        ).strip()

        has_letters = bool(
            re.search(r"[A-Za-zА-Яа-яЁё]{2,}", desc)
        )

        if match and has_letters:
            rows.append((desc, _num(match.group(1))))
            prev = None

        elif match and prev:
            rows.append((prev, _num(match.group(1))))
            prev = None

        elif match:
            rows.append(("", _num(match.group(1))))

        else:
            prev = desc if has_letters else None

    return [
        {
            "n": description,
            "a": amount,
            "c": categorize(description, cats, hist)
        }
        for description, amount in rows
    ]
