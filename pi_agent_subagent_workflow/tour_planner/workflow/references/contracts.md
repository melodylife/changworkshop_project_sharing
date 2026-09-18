# Artifact contracts

Downstream steps parse these files. Conform to them literally. When a value is
genuinely unknown, write `null` — **never** a plausible-looking guess.

All artifacts live under the run directory:

```
.pi/plans/YYYY-MM-DD-<slug>/
├── brief.json
├── evidence.json
├── research/
│   ├── poi.json
│   ├── weather.json
│   └── food.json
├── itinerary.json
├── itinerary.md
├── critique.md
├── design.md
├── shell.html
└── trip.html
```

---

## `brief.json` — Phase 0, written by the parent from the questionnaire

```json
{
  "destination": "<city, country>",
  "origin": "<home city>",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "party": { "adults": 2, "children": 0, "notes": "<体力 / 饮食等同行需求>" },
  "budget": { "level": "mid", "currency": "CNY", "per_person_total": 8000 },
  "pace": "relaxed",
  "interests": ["<兴趣 1>", "<兴趣 2>"],
  "hard_constraints": [
    "不要安排需要长时间步行的行程",
    "不在周一安排博物馆"
  ],
  "must_see": ["<必看清单>"],
  "must_avoid": ["<避开清单>"],
  "language": "zh",
  "notes": "<节奏偏好，例如每天几点开始>"
}
```

`pace` is one of `relaxed` (3–4 stops/day), `balanced` (4–6), `packed` (6–8).

---

## `research/*.json` — Phase 2, written by `researcher`

Every researcher writes the same envelope; only `category` and `records` differ.

```json
{
  "category": "poi",
  "destination": "<city, country>",
  "query": { "centre": [0.0, 0.0], "radius_m": 6000,
             "date_window": ["YYYY-MM-DD", "YYYY-MM-DD"] },
  "retrieved_at": "<ISO-8601 UTC>",
  "sources": [
    { "name": "Overpass API (OSM)", "url": "https://overpass-api.de/api/interpreter",
      "licence": "ODbL", "ok": true }
  ],
  "records": [
    {
      "id": "osm:node/<id>",
      "name": "<POI 名称>",
      "name_en": "<English name>",
      "category": "temple",
      "lat": 0.0,
      "lon": 0.0,
      "opening_hours": "06:00-18:00",
      "rank": 1,
      "why": "<一句话说明为什么选它>"
    }
  ],
  "unknowns": ["<未能确认的字段>"],
  "errors": []
}
```

**Rules**

- `lat` / `lon` are mandatory on every record. A record without coordinates is
  not usable — drop it or move it to `unknowns`.
- `opening_hours` keeps the raw OSM syntax verbatim, or `null`. Never translate
  it into prose and never infer it.
- `rank` is the researcher's ordering, 1 = best. Keep the list under ~20.
- `errors` records failed sources so the parent can see partial coverage
  instead of silently missing data.

---

## `itinerary.json` — Phase 3, written by `itinerary-synthesizer`

```json
{
  "trip": {
    "title": "<行程标题>",
    "destination": "<city, country>",
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "timezone": "<IANA tz>",
    "centre": [0.0, 0.0],
    "pace": "relaxed"
  },
  "days": [
    {
      "date": "YYYY-MM-DD",
      "theme": "<当天主题>",
      "weather": { "t_max_c": 17.2, "t_min_c": 9.8, "precip_mm": 0.4, "source": "Open-Meteo" },
      "stops": [
        {
          "start": "10:30",
          "name": "<景点名称>",
          "wiki": "<Q-id>",
          "lat": 0.0,
          "lon": 0.0,
          "duration_min": 90,
          "transport": null,
          "notes": "<一句话提示>",
          "sources": ["Overpass API (OSM)"]
        },
        {
          "start": "12:30",
          "name": "<午餐地点>",
          "lat": 0.0,
          "lon": 0.0,
          "duration_min": 60,
          "transport": { "mode": "walk", "minutes": 12 },
          "notes": null,
          "sources": ["Overpass API (OSM)"]
        }
      ]
    }
  ],
  "open_questions": [
    "<未能确认的条目>"
  ]
}
```

**Rules**

- `trip.pace` is copied verbatim from `brief.json`. `.pi/skills/trip-validate/validate_itinerary.py`
  reads it from here to budget stops per day, so it must not be omitted.
- `days` covers every date from `start_date` to `end_date` inclusive, with no
  gaps and no extras — including arrival and departure days.
- Every stop has `name`, `lat`, `lon`, `duration_min`, and `transport`.
  The first stop of each day uses `"transport": null`.
- `transport.mode` is one of `walk`, `transit`, `taxi`, `bike`, `train`.
- `sources` names the artifact or dataset each stop came from. A stop with no
  traceable source must not exist.
- `wiki` is **optional** but valuable: the Wikidata id of the place. When
  present, Phase 5a resolves the image in one batched request instead of
  guessing from the name. Carry it through from the research record when the
  synthesizer can identify the place unambiguously; omit it rather than guess.
- Anything unresolved goes in `open_questions`. This array is rendered into the
  final report's "需要你确认" section, so an honest gap is cheap and a
  confident invention is expensive.

---

## `images/manifest.json` — Phase 5a, written by `fetch_images.py`

Written by the script, **not** by a model. The generator reads it; the image
bytes behind it never enter a model context.

```json
{
  "generated_at": "<ISO-8601 UTC>",
  "tool": ".pi/skills/trip-images/fetch_images.py",
  "max_width": 640,
  "attribution_required": true,
  "images": [
    {
      "stop": "<stop 名称>",
      "day": "YYYY-MM-DD",
      "wikidata": "<Q-id>",
      "matched_by": "name-index(<stop 名称>)",
      "status": "ok",
      "file": "q<id>.jpg",
      "src": "images/q<id>.jpg",
      "commons_file": "<Commons 文件名>",
      "author": "<作者>",
      "licence": "CC BY-SA 4.0",
      "page": "https://commons.wikimedia.org/wiki/File:<Commons 文件名>",
      "bytes": 115200
    }
  ],
  "missing": ["<未命中图片的 stop>"],
  "total_bytes": 1218000
}
```

**Rules for the generator**

- Use `src` verbatim. Never construct an image path yourself.
- `status` must be `ok` (or the entry must be absent from `images`) before you
  emit a figure. `missing` and `download_failed` entries get **no** image block.
- `author` and `licence` go into the `figcaption` credit and into the credits
  footer. `attribution_required: true` is not advisory — Wikimedia images are
  CC-licensed or public domain, and the CC ones require attribution.
- Some entries legitimately have `author: null` (the metadata field was empty on
  Commons). Credit the licence, the Commons page, and Wikimedia Commons itself
  in that case; never omit the credit entirely.

**Rules for `embed_images.py`**

- Only `src="images/…"` is inlined. Remote, absolute and missing references are
  left untouched so the generator's self-check still catches external assets.
- Writes `<name>.embedded.html` by default; `--in-place` keeps a `.bak`.
