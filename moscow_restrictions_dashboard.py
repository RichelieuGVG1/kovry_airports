#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Дашборд ограничений на прилёт/вылет в аэропортах Москвы
(Шереметьево, Внуково, Домодедово, Жуковский) по экспорту Telegram-канала
«Говорит Росавиация» (Telegram Desktop → Export chat history → JSON, файл result.json).

Использование:
    python moscow_restrictions_dashboard.py result.json -o dashboard.html
    python moscow_restrictions_dashboard.py result.json -o dashboard.html --csv restrictions.csv
    python moscow_restrictions_dashboard.py result.json -o dashboard.html --d3 d3.v7.min.js   # офлайн

Скрипт:
  1. читает сообщения канала и находит введения/снятия ограничений по четырём аэропортам;
  2. склеивает их в «ограничения» (введение → снятие) по каждому аэропорту;
  3. сам определяет, какие годы, сезоны и месяцы есть в данных (появится 2027 — появятся
     кнопка 2027, его сезоны, месяцы и свечи на всех графиках);
  4. собирает один самодостаточный HTML-файл с тем же дашбордом и переключателями.

Нужен только Python 3.8+ (стандартная библиотека). Для просмотра — любой браузер;
библиотека d3 грузится с cdnjs, либо встраивается из файла через --d3.
"""
import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------- настройки разбора
AIRPORTS = {  # код: (регулярное выражение, название)
    'SVO': (r'шереметьев', 'Шереметьево'),
    'VKO': (r'внуков', 'Внуково'),
    'DME': (r'домодедов', 'Домодедово'),
    'ZIA': (r'жуковск|раменск', 'Жуковский'),
}
# Сообщения-сводки, новости, сообщения авиакомпаний и погодные ограничения не являются
# сообщениями о введении/снятии и пропускаются целиком.
SKIP = (r'погодн|снегопад|ветра|метеоусл|гроза|туман|Минтранс|Минувшей ночью|По данным на|'
        r'Сообщение авиакомпании|Аэрофлот|Победа|Вниманию пассажиров|НЕ соответствует|'
        r'НЕ сообщала|закрепленных|Продолжаем информировать|Информируем о работе|'
        r'Работа гражданской авиации|С начала суток|Аномальный|Air Arabia|Як-40|'
        r'Уважаемые пассажиры|В период минувших')
LIFT = r'снят|сняли|возобнов|штатн|открыт|без ограничений|вернул'
INTRO = r'введен|ввели|закрыт|не принима|не отправля|по согласованию|корректировк'
PAST = r'был\w* необходим|вводили|вводились|ввели для|Ограничения необходимы'
MONTHS_RU = {'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4, 'ма[йя]': 5, 'июн': 6, 'июл': 7,
             'август': 8, 'сентябр': 9, 'октябр': 10, 'ноябр': 11, 'декабр': 12}
SEASON = {12: 'Зима', 1: 'Зима', 2: 'Зима', 3: 'Весна', 4: 'Весна', 5: 'Весна',
          6: 'Лето', 7: 'Лето', 8: 'Лето', 9: 'Осень', 10: 'Осень', 11: 'Осень'}
MONTH_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
             'сентября', 'октября', 'ноября', 'декабря']
MONTH_NOM = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август',
             'сентябрь', 'октябрь', 'ноябрь', 'декабрь']

# До мая 2025 канал публиковал итоговые сводки свободным текстом («вводились ограничения
# с 11:33 до 14:00»). Эти эпизоды разобраны вручную по самим сообщениям канала.
# Формат: (аэропорт, начало или None, конец).
EARLY_EVENTS = [
    ('DME', '2023-12-19T11:33', '2023-12-19T14:00'), ('VKO', '2023-12-19T11:50', '2023-12-19T14:00'),
    ('SVO', '2024-01-18T14:03', '2024-01-18T14:10'),
    *[(a, '2024-03-17T09:39', '2024-03-17T11:15') for a in ('VKO', 'DME', 'ZIA')],
    *[(a, '2024-05-27T20:46', '2024-05-27T21:20') for a in ('DME', 'ZIA')],
    *[(a, '2024-08-21T02:31', '2024-08-21T06:30') for a in ('VKO', 'DME', 'ZIA')],
    *[(a, None, '2024-09-01T09:05') for a in ('VKO', 'DME', 'ZIA')],
    ('VKO', '2024-09-10T01:17', '2024-09-10T07:58'), ('DME', '2024-09-10T01:17', '2024-09-10T07:58'),
    ('ZIA', '2024-09-10T01:46', '2024-09-10T07:58'),
    ('DME', '2024-11-10T08:03', '2024-11-10T10:32'), ('ZIA', '2024-11-10T08:03', '2024-11-10T10:32'),
    ('SVO', '2024-11-10T09:45', '2024-11-10T10:32'),
    *[(a, '2024-12-26T16:08', '2024-12-26T16:39') for a in ('SVO', 'DME', 'VKO', 'ZIA')],
    ('DME', '2025-01-24T00:22', '2025-01-24T02:12'), ('ZIA', '2025-01-24T00:22', '2025-01-24T02:12'),
    ('VKO', '2025-01-24T01:32', '2025-01-24T02:12'),
    ('SVO', '2025-02-28T02:41', '2025-02-28T03:45'),
    ('ZIA', '2025-03-11T04:24', '2025-03-11T10:15'), ('DME', '2025-03-11T04:40', '2025-03-11T10:15'),
    ('SVO', '2025-03-11T04:40', '2025-03-11T08:55'), ('VKO', '2025-03-11T07:15', '2025-03-11T10:15'),
    ('VKO', '2025-03-14T06:13', '2025-03-14T07:27'),
    *[(a, '2025-04-04T00:30', '2025-04-04T02:24') for a in ('VKO', 'DME', 'ZIA')],
    ('VKO', '2025-04-09T23:00', '2025-04-09T23:05'),
    ('ZIA', '2025-04-24T01:00', '2025-04-24T02:39'),
]


# ---------------------------------------------------------------- разбор сообщений
def message_text(msg):
    t = msg.get('text', '')
    if isinstance(t, list):
        t = ''.join(p if isinstance(p, str) else p.get('text', '') for p in t)
    return t or ''


def airports_in(sentence):
    if re.search('запасн', sentence, re.I):  # «ушёл на запасной аэродром Внуково» — не про Внуково
        return []
    return [code for code, (rx, _) in AIRPORTS.items() if re.search(rx, sentence, re.I)]


def event_time(unit, posted):
    """Время события из текста («в 04:40 МСК», «с 11:49 МСК 19 мая»), иначе — время публикации."""
    m = re.search(r'\b[вВсС]\s+(\d{1,2})[:.](\d{2})', unit) or \
        re.search(r'(\d{1,2})[:.](\d{2})\s*(?:МСК|мск)', unit)
    if not m or re.search(r'по данным на|\bдо\s+\d', unit[max(0, m.start() - 8):m.end()], re.I):
        return posted
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return posted
    dm = re.search(r'(\d{1,2})\s+(' + '|'.join(MONTHS_RU) + r')\w*', unit[m.end():m.end() + 20], re.I)
    if dm:
        mon = next(v for k, v in MONTHS_RU.items() if re.match(k, dm.group(2), re.I))
        try:
            return dt.datetime(posted.year, mon, int(dm.group(1)), h, mi)
        except ValueError:
            return posted
    cands = [dt.datetime.combine(posted.date() + dt.timedelta(days=k), dt.time(h, mi)) for k in (-1, 0, 1)]
    return min(cands, key=lambda z: abs((z - posted).total_seconds()))


def extract_events(messages, auto_from):
    """События (время, аэропорт, 'in'/'out', 'full'/'partial', id сообщения) из сообщений начиная с auto_from."""
    events = []
    for msg in messages:
        if msg.get('type') != 'message' or not msg.get('date'):
            continue
        posted = dt.datetime.fromisoformat(msg['date'])
        if posted < auto_from:
            continue
        text = message_text(msg)
        if not re.search('ограничен', text, re.I) or re.search(SKIP, text):
            continue
        if not any(re.search(rx, text, re.I) for rx, _ in AIRPORTS.values()):
            continue
        units = [u.strip() for line in text.split('\n')
                 for u in re.split(r'(?<=[.!;])\s+', line) if u.strip()]
        acc, last_action = [], False
        for u in units:
            found = airports_in(u)
            is_list = bool(re.match(r'^[–—\-]', u)) or (
                bool(re.search(r'Аэропорт', u)) and not re.search(LIFT + '|' + INTRO, u, re.I))
            if re.search(PAST, u, re.I) and not re.search(r'снят|СНЯТ', u):
                continue
            if re.search(r'по согласованию', u, re.I):
                act = 'in'
            elif re.search(LIFT, u, re.I):
                act = 'out'
            elif re.search(INTRO, u, re.I):
                act = 'in'
            else:
                act = None
            if act is None:
                if is_list or found:
                    if last_action:
                        acc, last_action = [], False
                    acc += [z for z in found if z not in acc]
                continue
            targets = found if found else acc
            when = event_time(u, posted)
            kind = 'partial' if re.search(r'по согласованию|корректировк', u, re.I) else 'full'
            for ap in targets:
                events.append((when, ap, act, kind, msg.get('id')))
            last_action = True
            if found:
                acc = found[:]
    events.sort(key=lambda e: (e[0], e[4] or 0))
    return events


def build_episodes(events, gap_hours, max_hours):
    """Склеивает введения и снятия в ограничения по каждому аэропорту."""
    open_, episodes, orphan = {}, [], 0
    for when, ap, act, kind, mid in events:
        if act == 'in':
            # новое введение спустя долгое время без снятия: снятие не публиковали
            if ap in open_ and (when - open_[ap]['last']).total_seconds() > gap_hours * 3600:
                o = open_.pop(ap); o['end'] = None; episodes.append(o)
            if ap not in open_:
                open_[ap] = dict(ap=ap, start=when, end=None, kinds={kind}, last=when)
            else:
                open_[ap]['kinds'].add(kind); open_[ap]['last'] = when
        else:
            if ap in open_:
                o = open_.pop(ap); o['end'] = when; episodes.append(o)
            else:
                orphan += 1
    episodes.extend(open_.values())
    for o in episodes:
        d = (o['end'] - o['start']).total_seconds() / 60 if o['end'] and o['start'] else None
        o['dur'] = d if d is not None and 0 <= d <= max_hours * 60 else None
    return episodes, orphan


def early_episodes(first_msg_date, auto_from):
    out = []
    for ap, s, e in EARLY_EVENTS:
        end = dt.datetime.fromisoformat(e)
        start = dt.datetime.fromisoformat(s) if s else None
        if end < first_msg_date or (start or end) >= auto_from:
            continue
        out.append(dict(ap=ap, start=start, end=end, kinds={'full'},
                        dur=(end - start).total_seconds() / 60 if start else None))
    return out


def to_rows(episodes):
    rows = []
    for o in sorted(episodes, key=lambda o: o['start'] or o['end']):
        s = o['start'] or o['end']
        rows.append(dict(
            airport=AIRPORTS[o['ap']][1],
            start=o['start'].strftime('%Y-%m-%d %H:%M') if o['start'] else None,
            end=o['end'].strftime('%Y-%m-%d %H:%M') if o['end'] else None,
            duration_min=round(o['dur'], 1) if o['dur'] is not None else None,
            kind='частичное' if o['kinds'] == {'partial'} else 'полное',
            year=s.year, month=s.month, season=SEASON[s.month],
            hour=o['start'].hour if o['start'] else None,
            date=s.strftime('%Y-%m-%d'), weekday=s.weekday()))
    for i, r in enumerate(rows):
        r['id'] = i + 1
    return rows


def ru_date(d):
    return f'{d.day} {MONTH_GEN[d.month - 1]} {d.year}'


def print_summary(rows, orphan):
    if not rows:
        print('Ограничений в московских аэропортах не найдено.')
        return
    hours = Counter(r['hour'] for r in rows if r['hour'] is not None)
    months = Counter(r['date'][:7] for r in rows)
    wd = Counter(r['weekday'] for r in rows)
    durs = sorted(r['duration_min'] for r in rows if r['duration_min'] is not None)
    med = durs[len(durs) // 2] if durs else None
    names = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    print(f'Введений ограничений: {len(rows)} за {len({r["date"] for r in rows})} дн.')
    print('По годам:', dict(sorted(Counter(r["year"] for r in rows).items())))
    print('Самые частые часы:', ', '.join(f'{h:02d}:00 ({n})' for h, n in hours.most_common(5)))
    print('Самые напряжённые месяцы:', ', '.join(f'{k} ({n})' for k, n in months.most_common(5)))
    print('По дням недели:', ', '.join(f'{names[k]} {wd[k]}' for k in range(7)))
    if med is not None:
        print(f'Продолжительность: медиана {med:.0f} мин, среднее {sum(durs)/len(durs):.0f} мин, '
              f'известна у {len(durs)} из {len(rows)}')
    print(f'Сообщений о снятии без найденного введения: {orphan}')


# ---------------------------------------------------------------- шаблон страницы (разметка, стили, расчёты и графики)
TEMPLATE_BODY = r'''<style>
.mr{font-family:var(--font-anthropic-sans);color:var(--color-fg);display:flex;flex-direction:column;gap:var(--cds-gap-xl)}
.mr h1{font-family:var(--font-anthropic-serif);font-weight:400;font-size:var(--cds-font-size-title);margin:0}
.mr h2{font-size:var(--cds-font-size-heading);font-weight:var(--cds-font-weight-medium);margin:0 0 var(--cds-gap-sm)}
.mr h3{font-size:var(--cds-font-size-body);font-weight:var(--cds-font-weight-medium);margin:0}
.mr p{margin:0}
.mr .lead{color:var(--color-fg-muted);max-width:60rem;margin-top:var(--cds-gap-sm)}
.mr .lead b,.mr .sum b{font-weight:600;color:var(--color-fg)}
.mr .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,11rem),1fr));gap:var(--cds-gap-md)}
.mr .tile,.mr .card{background:var(--color-panel);border:1px solid var(--color-border-line);border-radius:var(--cds-radius);padding:var(--cds-pad-lg)}
.mr .tile .lab{font-size:var(--cds-font-size-caption);color:var(--color-fg-muted)}
.mr .tile .big{font-family:var(--font-anthropic-serif);font-weight:400;font-size:var(--cds-font-size-title);font-variant-numeric:tabular-nums;margin-top:var(--cds-gap-xs)}
.mr .tile .unit{font-size:var(--cds-font-size-body);color:var(--color-fg-muted);margin-left:.25em;font-family:var(--font-anthropic-sans)}
.mr .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,22rem),1fr));gap:var(--cds-gap-md)}
.mr .note{font-size:var(--cds-font-size-caption);color:var(--color-fg-muted);margin:var(--cds-gap-xs) 0 var(--cds-gap-sm)}
.mr .chart{position:relative;min-height:240px;width:100%}
.mr .chart.tall{min-height:280px}
.mr .chart.short{min-height:200px}
.mr svg text{font-family:var(--font-anthropic-sans);font-size:var(--cds-font-size-caption);fill:var(--color-fg-muted)}
.mr svg .ann{fill:var(--color-fg)}
.mr .tip{position:absolute;pointer-events:none;background:var(--cds-surface-popover);border:1px solid var(--cds-border);border-radius:var(--cds-radius);box-shadow:var(--cds-shadow-popover);padding:var(--cds-pad-xs) var(--cds-pad-sm);font-size:var(--cds-font-size-caption);white-space:nowrap;z-index:5;font-variant-numeric:tabular-nums}
.mr .tip .t0{color:var(--cds-text-secondary);margin-bottom:2px}
.mr .controls{display:flex;flex-wrap:wrap;gap:var(--cds-gap-md);align-items:center;margin-bottom:var(--cds-gap-md)}
.mr .seg{display:inline-flex;border:1px solid var(--color-border-line);border-radius:var(--cds-radius);overflow:hidden}
.mr .seg button{font:inherit;font-size:var(--cds-font-size-body);background:transparent;color:var(--color-fg);border:0;padding:var(--cds-pad-xs) var(--cds-pad-md);cursor:pointer}
.mr .seg button+button{border-left:1px solid var(--color-border-line)}
.mr .seg button:disabled{opacity:.4;cursor:default}
.mr .seg{flex-wrap:wrap}
.mr .seg button[aria-pressed="true"]{background:var(--color-fg);color:var(--color-bg)}
.mr .sum{margin-bottom:var(--cds-gap-md);color:var(--color-fg-muted)}
.mr .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,20rem),1fr));gap:var(--cds-gap-md);margin-bottom:var(--cds-gap-md)}
.mr .srow{display:flex;justify-content:space-between;gap:var(--cds-gap-md);padding:var(--cds-pad-xs) 0;border-bottom:1px solid var(--color-border-line);font-variant-numeric:tabular-nums}
.mr .srow:last-child{border-bottom:0}
.mr .sl{color:var(--color-fg-muted)}
.mr .sv{font-family:var(--font-anthropic-serif);font-size:var(--cds-font-size-heading)}
.mr .lab{margin-bottom:var(--cds-gap-xs)}
.mr .mr-dur [hidden],.mr [hidden]{display:none}
.mr .tbl{max-height:22rem;overflow:auto}
.mr table{border-collapse:collapse;width:100%;font-size:var(--cds-font-size-body);font-variant-numeric:tabular-nums}
.mr th{text-align:left;font-weight:var(--cds-font-weight-medium);color:var(--color-fg-muted);font-size:var(--cds-font-size-caption);position:sticky;top:0;background:var(--color-panel);padding:var(--cds-pad-xs) var(--cds-pad-sm);border-bottom:1px solid var(--color-border-line)}
.mr td{padding:var(--cds-pad-xs) var(--cds-pad-sm);border-bottom:1px solid var(--color-border-line)}
.mr td.num,.mr th.num{text-align:right}
.mr .method{font-size:var(--cds-font-size-caption);color:var(--color-fg-muted);max-width:60rem;display:flex;flex-direction:column;gap:var(--cds-gap-xs)}
.mr [data-dash-source-state=empty]{color:transparent}
.mr [data-dash-source-state=refreshing]{opacity:.5;transition:opacity var(--cds-dur-slow)}
</style>

<div class="mr">
  <header id="top">
    <h1>Ограничения на прилёт и вылет в аэропортах Москвы</h1>
    <p class="lead">Шереметьево, Внуково, Домодедово и Жуковский по сообщениям канала «Говорит Росавиация», __PERIOD__. Чаще всего ограничения вводили в <b data-draw="k-peak" data-source="kpi" data-field="peak_hour_label" data-row="0">—</b>, больше всего их было в <b data-draw="k-topm" data-source="kpi" data-field="top_month_label" data-row="0">—</b>, а от введения до снятия в среднем (медиана) проходило <b data-draw="k-med2" data-source="kpi" data-field="median_dur" data-row="0">—</b> мин.</p>
  </header>

  <div class="tiles" id="kpis">
    <div class="tile"><div class="lab">Введено ограничений (по аэропортам)</div><div class="big"><span data-draw="k-total" data-source="kpi" data-field="total" data-row="0">—</span></div></div>
    <div class="tile"><div class="lab">Дней с ограничениями</div><div class="big"><span data-draw="k-days" data-source="kpi" data-field="days" data-row="0">—</span></div></div>
    <div class="tile"><div class="lab">Медиана продолжительности</div><div class="big"><span data-draw="k-med" data-source="kpi" data-field="median_dur" data-row="0">—</span><span class="unit">мин</span></div></div>
    <div class="tile"><div class="lab">Введено ночью, 00:00–06:00</div><div class="big"><span data-draw="k-night" data-source="kpi" data-field="night_pct" data-row="0">—</span><span class="unit">%</span></div></div>
  </div>

  <section id="overview">
    <h2>Общая картина</h2>
    <div class="card" id="card-months">
      <h3>Введённые ограничения по месяцам, с января __FIRST_YEAR__</h3>
      <p class="note">Число введений по всем четырём аэропортам. __EXPORT_NOTE__ Наведите на столбец, чтобы увидеть месяц и число дней.</p>
      <div class="chart" data-draw="months-all" data-source="months_all"></div>
    </div>
    <div class="card" id="card-topdays" style="margin-top:var(--cds-gap-md)">
      <h3>Дни с наибольшим числом введённых ограничений</h3>
      <p class="note">Десять дат с наибольшим числом введений по четырём аэропортам.</p>
      <div class="tbl">
        <table data-source="top_days" data-row-key="date">
          <thead><tr><th data-field="date">Дата</th><th data-field="weekday_name">День</th><th class="num" data-field="n">Введений</th><th data-field="airports">Аэропорты</th></tr></thead>
          <tbody data-draw="top-days"></tbody>
        </table>
      </div>
    </div>
  </section>

  <section id="seasons">
    <h2>По годам, сезонам и месяцам</h2>
    <div class="controls">
      <div class="seg" role="group" aria-label="Показатель">
        <button type="button" class="mr-metric" data-metric="count">Количество</button><button type="button" class="mr-metric" data-metric="duration">Продолжительность</button>
      </div>
      <div class="seg" role="group" aria-label="Статистика">
        <button type="button" class="mr-stat" data-stat="mean">Среднее</button><button type="button" class="mr-stat" data-stat="median">Медиана</button>
      </div>
      <div class="seg" role="group" aria-label="Период">
        <button type="button" class="mr-all" data-all="0">Выбранный период</button><button type="button" class="mr-all" data-all="1">За всё время</button>
      </div>
      <div class="seg mr-pick" role="group" aria-label="Год">
        __YEAR_BUTTONS__
      </div>
      <div class="seg mr-pick" role="group" aria-label="Сезон">
        <button type="button" class="mr-season" data-season="Зима">Зима</button><button type="button" class="mr-season" data-season="Весна">Весна</button><button type="button" class="mr-season" data-season="Лето">Лето</button><button type="button" class="mr-season" data-season="Осень">Осень</button>
      </div>
      <div class="seg mr-pick" role="group" aria-label="Месяц">
        <button type="button" class="mr-month" data-month="0" data-seasonof="*">Весь сезон</button><button type="button" class="mr-month" data-month="1" data-seasonof="Зима">Январь</button><button type="button" class="mr-month" data-month="2" data-seasonof="Зима">Февраль</button><button type="button" class="mr-month" data-month="3" data-seasonof="Весна">Март</button><button type="button" class="mr-month" data-month="4" data-seasonof="Весна">Апрель</button><button type="button" class="mr-month" data-month="5" data-seasonof="Весна">Май</button><button type="button" class="mr-month" data-month="6" data-seasonof="Лето">Июнь</button><button type="button" class="mr-month" data-month="7" data-seasonof="Лето">Июль</button><button type="button" class="mr-month" data-month="8" data-seasonof="Лето">Август</button><button type="button" class="mr-month" data-month="9" data-seasonof="Осень">Сентябрь</button><button type="button" class="mr-month" data-month="10" data-seasonof="Осень">Октябрь</button><button type="button" class="mr-month" data-month="11" data-seasonof="Осень">Ноябрь</button><button type="button" class="mr-month" data-month="12" data-seasonof="Зима">Декабрь</button>
      </div>
    </div>
    <p class="sum mr-sum-has">Период — <b data-draw="sel-label">—</b>: <b data-draw="s-n" data-source="scope_sum" data-field="n">—</b> введённых ограничений за <b data-draw="s-days" data-source="scope_sum" data-field="days">—</b> дн., чаще всего в <b data-draw="s-peak" data-source="scope_sum" data-field="peak_hour_label">—</b>, медианная продолжительность <b data-draw="s-med" data-source="scope_sum" data-field="median_dur">—</b> мин.</p>
    <p class="sum mr-sum-none" hidden>В этом периоде сообщений о введении ограничений в московских аэропортах в выгрузке нет.</p>
    <div class="stats" id="period-stats">
      <div class="tile">
        <div class="lab">Количество ограничений за день с ограничениями</div>
        <div class="srow"><span class="sl">Среднее</span><span class="sv"><span data-draw="st-dmean" data-source="scope_sum" data-field="day_mean">—</span></span></div>
        <div class="srow"><span class="sl">Медиана</span><span class="sv"><span data-draw="st-dmed" data-source="scope_sum" data-field="day_median">—</span></span></div>
        <div class="srow"><span class="sl">Разброс, мин – макс</span><span class="sv"><span data-draw="st-dmin" data-source="scope_sum" data-field="day_min">—</span> – <span data-draw="st-dmax" data-source="scope_sum" data-field="day_max">—</span></span></div>
        <div class="srow"><span class="sl">Всего введений</span><span class="sv"><span data-draw="st-n" data-source="scope_sum" data-field="n">—</span></span></div>
      </div>
      <div class="tile">
        <div class="lab">Продолжительность одного ограничения, мин</div>
        <div class="srow"><span class="sl">Среднее</span><span class="sv"><span data-draw="st-mean" data-source="scope_sum" data-field="mean_dur">—</span></span></div>
        <div class="srow"><span class="sl">Медиана</span><span class="sv"><span data-draw="st-med" data-source="scope_sum" data-field="median_dur">—</span></span></div>
        <div class="srow"><span class="sl">Разброс, мин – макс</span><span class="sv"><span data-draw="st-min" data-source="scope_sum" data-field="min_dur">—</span> – <span data-draw="st-max" data-source="scope_sum" data-field="max_dur">—</span></span></div>
        <div class="srow"><span class="sl">С известной продолжительностью</span><span class="sv"><span data-draw="st-dn" data-source="scope_sum" data-field="dur_n">—</span></span></div>
      </div>
    </div>
    <div class="grid">
      <div class="card" id="card-season-hours">
        <h3><span class="mr-mc">Количество ограничений по часам суток — свечи</span><span class="mr-md" hidden>Продолжительность ограничений по часу введения — свечи</span></h3>
        <p class="note mr-mc">Столбец — <span class="mr-st-mean">среднее</span><span class="mr-st-med" hidden>медиана</span> число введений в этот час за день с ограничениями (переключатель «Среднее / Медиана»), «фитиль» — минимум и максимум за один день периода.</p>
        <p class="note mr-md" hidden>Для ограничений, введённых в этот час: столбец — <span class="mr-st-mean">средняя</span><span class="mr-st-med" hidden>медианная</span> продолжительность, фитиль — самое короткое и самое длинное.</p>
        <div class="chart tall" data-draw="season-hours" data-source="scope_hours"></div>
      </div>
      <div class="card" id="card-season-months">
        <h3><span class="mr-mc">Количество ограничений по месяцам — свечи</span><span class="mr-md" hidden>Продолжительность ограничений по месяцам — свечи</span></h3>
        <p class="note mr-mc">Столбец — <span class="mr-st-mean">среднее</span><span class="mr-st-med" hidden>медиана</span> число введений за день с ограничениями, фитиль — минимум и максимум за день. При выбранном сезоне над свечой — всего введений и дней; выбранный месяц выделен. «За всё время» — все месяцы с января __FIRST_YEAR__.</p>
        <p class="note mr-md" hidden>Столбец — <span class="mr-st-mean">средняя</span><span class="mr-st-med" hidden>медианная</span> продолжительность, фитиль — самое короткое и самое длинное ограничение месяца. Выбранный месяц выделен. «За всё время» — все месяцы с января __FIRST_YEAR__.</p>
        <div class="chart tall" data-draw="season-months" data-source="monthly months_all"></div>
      </div>
      <div class="card" id="card-hours">
        <h3>Час введения ограничения</h3>
        <p class="note">Сколько ограничений введено в каждый час суток (МСК) за выбранный период.</p>
        <div class="chart" data-draw="hours-all" data-source="scope_hours"></div>
      </div>
      <div class="card" id="card-hours-dur">
        <h3>Продолжительность по часу введения</h3>
        <p class="note">Сколько в <span class="mr-st-mean">среднем</span><span class="mr-st-med" hidden>медиане</span> длились ограничения, введённые в этот час суток (МСК), за выбранный период. Переключатель «Среднее / Медиана» меняет высоту столбцов; в подсказке — оба значения и разброс.</p>
        <div class="chart" data-draw="hours-dur" data-source="scope_hours"></div>
      </div>
      <div class="card" id="card-weekdays">
        <h3><span class="mr-mc">Количество ограничений по дню недели</span><span class="mr-md" hidden>Продолжительность ограничений по дню недели</span></h3>
        <p class="note mr-mc">Столбец — <span class="mr-st-mean">среднее</span><span class="mr-st-med" hidden>медиана</span> число введений за такой день недели с ограничениями, фитиль — минимум и максимум; всего — в подсказке.</p>
        <p class="note mr-md" hidden>Для ограничений, начавшихся в этот день недели: столбец — <span class="mr-st-mean">средняя</span><span class="mr-st-med" hidden>медианная</span> продолжительность, фитиль — минимум и максимум.</p>
        <div class="chart" data-draw="weekdays" data-source="scope_weekdays"></div>
      </div>
      <div class="card" id="card-bins">
        <h3>Сколько длились ограничения</h3>
        <p class="note">Время от введения до снятия за выбранный период, только для ограничений, у которых в канале есть оба сообщения.</p>
        <div class="chart" data-draw="dur-bins" data-source="scope_bins"></div>
      </div>
    </div>
  </section>

  <section id="durations">
    <h2>Продолжительность ограничений по сезонам</h2>
    <div class="card" id="card-durations">
      <p class="note">Часы от введения до снятия. Тело свечи — от 25-го до 75-го процентиля, линия внутри — медиана, точка — среднее, фитиль — минимум и максимум. З — зима (январь, февраль, декабрь), В — весна, Л — лето, О — осень.</p>
      <div class="chart tall" data-draw="dur-season" data-source="dur_season"></div>
    </div>
  </section>

  <section class="method" id="method">
    <h3>Как считалось</h3>
    <p>Одно «ограничение» — введение ограничений в одном аэропорту: если закрыли сразу три аэропорта, это три ограничения. Учтены и полное закрытие, и работа «по согласованию с соответствующими органами»; если частичный режим сменял полный без снятия, это одно ограничение.</p>
    <p>Время введения и снятия берётся из текста сообщения («в 04:40 МСК»), а если его нет — из времени публикации. Продолжительность считается только там, где есть и сообщение о введении, и о снятии; если снятие не было опубликовано или прошло больше суток, продолжительность не считается.</p>
    <p>Сезоны — внутри календарного года: зима = январь, февраль и декабрь того же года. __METHOD_NOTE__ Сообщения о погодных ограничениях не учитывались.</p>
  </section>
</div>

<script>
// ---------- calculations ----------
// Периоды (scope): 'all' — всё время; 'год|сезон'; 'год|сезон|месяц'.
dash.calc('kpi', {
  inputs: ['restrictions'],
  title: 'Итоговые показатели',
  description: 'Число введений, дней, медиана продолжительности, доля ночных, пиковый час и месяц.',
  fn: (restrictions) => {
    const MN = ['январе','феврале','марте','апреле','мае','июне','июле','августе','сентябре','октябре','ноябре','декабре'];
    const durs = restrictions.map(r => r.duration_min).filter(v => v != null).sort((a, b) => a - b);
    const med = durs.length ? (durs.length % 2 ? durs[(durs.length - 1) / 2] : (durs[durs.length / 2 - 1] + durs[durs.length / 2]) / 2) : null;
    const hrs = restrictions.filter(r => r.hour != null);
    const hc = new Array(24).fill(0); hrs.forEach(r => hc[r.hour]++);
    const ph = hc.indexOf(Math.max(...hc));
    const mc = {}; restrictions.forEach(r => { const k = r.date.slice(0, 7); mc[k] = (mc[k] || 0) + 1; });
    const tm = Object.keys(mc).sort((a, b) => mc[b] - mc[a])[0];
    const p = (n) => String(n).padStart(2, '0');
    return [{
      total: restrictions.length,
      days: new Set(restrictions.map(r => r.date)).size,
      median_dur: med == null ? null : Math.round(med),
      night_pct: Math.round(100 * hrs.filter(r => r.hour < 6).length / hrs.length),
      peak_hour_label: p(ph) + ':00–' + p((ph + 1) % 24) + ':00',
      top_month_label: MN[+tm.slice(5) - 1] + ' ' + tm.slice(0, 4) + ' г.',
    }];
  },
});

dash.calc('months_all', {
  inputs: ['restrictions'],
  title: 'Введения по месяцам',
  description: 'Для каждого месяца с января первого года: введений, дней, среднее, медиана, минимум и максимум за день, статистика продолжительности (мин).',
  fn: (restrictions) => {
    const R1 = (v) => v == null ? null : Math.round(v * 10) / 10;
    const med = (s) => { if (!s.length) return null; const a = [...s].sort((x, y) => x - y), k = a.length; return k % 2 ? a[(k - 1) / 2] : (a[k / 2 - 1] + a[k / 2]) / 2; };
    const cnt = (c) => ({ mean: c.length ? Math.round(100 * c.reduce((a, b) => a + b, 0) / c.length) / 100 : 0, median: c.length ? med(c) : 0, min: c.length ? Math.min(...c) : 0, max: c.length ? Math.max(...c) : 0 });
    const mix = (a, b, c) => { for (const k in b) a[k] = b[k]; for (const k in c) a[k] = c[k]; return a; };
    const dur = (rs) => { const d = rs.map(r => r.duration_min).filter(v => v != null); return { d_n: d.length, d_mean: d.length ? R1(d.reduce((a, b) => a + b, 0) / d.length) : null, d_median: R1(med(d)), d_min: d.length ? R1(Math.min(...d)) : null, d_max: d.length ? R1(Math.max(...d)) : null }; };
    const last = restrictions.map(r => r.date.slice(0, 7)).sort().pop();
    let y = window.MR_YEARS[0], m = 1; const [y2, m2] = last.split('-').map(Number);
    const out = [];
    while (y < y2 || (y === y2 && m <= m2)) {
      const k = y + '-' + String(m).padStart(2, '0');
      const rs = restrictions.filter(r => r.date.slice(0, 7) === k);
      const per = {}; rs.forEach(r => { per[r.date] = (per[r.date] || 0) + 1; });
      const c = Object.values(per);
      out.push(mix({ ym: k, year: y, month: m, n: rs.length, days: c.length }, cnt(c), dur(rs)));
      m++; if (m > 12) { m = 1; y++; }
    }
    return out;
  },
});

dash.calc('top_days', {
  inputs: ['restrictions'],
  title: 'Самые напряжённые дни',
  description: 'Десять дат с наибольшим числом введений.',
  fn: (restrictions) => {
    const N = ['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье'];
    const g = {};
    restrictions.forEach(r => { (g[r.date] = g[r.date] || { n: 0, a: new Set(), w: r.weekday }).n++; g[r.date].a.add(r.airport); });
    return Object.keys(g).sort((x, y) => g[y].n - g[x].n || (x < y ? 1 : -1)).slice(0, 10)
      .map(date => ({ date, weekday_name: N[g[date].w], n: g[date].n, airports: [...g[date].a].sort().join(', ') }));
  },
});

dash.calc('scope_hours', {
  inputs: ['restrictions'],
  title: 'Часы по периодам',
  description: 'Для каждого периода и часа: всего введений, среднее, медиана, минимум и максимум за день; статистика продолжительности (мин).',
  fn: (restrictions) => {
    const R1 = (v) => v == null ? null : Math.round(v * 10) / 10;
    const med = (s) => { if (!s.length) return null; const a = [...s].sort((x, y) => x - y), k = a.length; return k % 2 ? a[(k - 1) / 2] : (a[k / 2 - 1] + a[k / 2]) / 2; };
    const cnt = (c) => ({ mean: c.length ? Math.round(100 * c.reduce((a, b) => a + b, 0) / c.length) / 100 : 0, median: c.length ? med(c) : 0, min: c.length ? Math.min(...c) : 0, max: c.length ? Math.max(...c) : 0 });
    const mix = (a, b, c) => { for (const k in b) a[k] = b[k]; for (const k in c) a[k] = c[k]; return a; };
    const dur = (rs) => { const d = rs.map(r => r.duration_min).filter(v => v != null); return { d_n: d.length, d_mean: d.length ? R1(d.reduce((a, b) => a + b, 0) / d.length) : null, d_median: R1(med(d)), d_min: d.length ? R1(Math.min(...d)) : null, d_max: d.length ? R1(Math.max(...d)) : null }; };
    const SM = { 'Зима': [1, 2, 12], 'Весна': [3, 4, 5], 'Лето': [6, 7, 8], 'Осень': [9, 10, 11] };
    const scopes = [['all', restrictions]];
    window.MR_YEARS.forEach(y => Object.keys(SM).forEach(se => {
      const rs = restrictions.filter(r => r.year === y && r.season === se);
      scopes.push([y + '|' + se, rs]);
      SM[se].forEach(m => scopes.push([y + '|' + se + '|' + m, rs.filter(r => r.month === m)]));
    }));
    const out = [];
    scopes.forEach(([scope, rs]) => {
      const days = [...new Set(rs.map(r => r.date))];
      for (let hour = 0; hour < 24; hour++) {
        const hr = rs.filter(r => r.hour === hour); const per = {}; hr.forEach(r => { per[r.date] = (per[r.date] || 0) + 1; });
        const c = days.map(d => per[d] || 0);
        out.push(mix({ key: scope + '|' + hour, scope, hour, n: hr.length, days: days.length }, cnt(c), dur(hr)));
      }
    });
    return out;
  },
});

dash.calc('scope_weekdays', {
  inputs: ['restrictions'],
  title: 'Дни недели по периодам',
  description: 'Для каждого периода и дня недели: всего введений, среднее, медиана, минимум и максимум за такой день с ограничениями; статистика продолжительности (мин).',
  fn: (restrictions) => {
    const R1 = (v) => v == null ? null : Math.round(v * 10) / 10;
    const med = (s) => { if (!s.length) return null; const a = [...s].sort((x, y) => x - y), k = a.length; return k % 2 ? a[(k - 1) / 2] : (a[k / 2 - 1] + a[k / 2]) / 2; };
    const cnt = (c) => ({ mean: c.length ? Math.round(100 * c.reduce((a, b) => a + b, 0) / c.length) / 100 : 0, median: c.length ? med(c) : 0, min: c.length ? Math.min(...c) : 0, max: c.length ? Math.max(...c) : 0 });
    const mix = (a, b, c) => { for (const k in b) a[k] = b[k]; for (const k in c) a[k] = c[k]; return a; };
    const dur = (rs) => { const d = rs.map(r => r.duration_min).filter(v => v != null); return { d_n: d.length, d_mean: d.length ? R1(d.reduce((a, b) => a + b, 0) / d.length) : null, d_median: R1(med(d)), d_min: d.length ? R1(Math.min(...d)) : null, d_max: d.length ? R1(Math.max(...d)) : null }; };
    const SM = { 'Зима': [1, 2, 12], 'Весна': [3, 4, 5], 'Лето': [6, 7, 8], 'Осень': [9, 10, 11] };
    const scopes = [['all', restrictions]];
    window.MR_YEARS.forEach(y => Object.keys(SM).forEach(se => {
      const rs = restrictions.filter(r => r.year === y && r.season === se);
      scopes.push([y + '|' + se, rs]);
      SM[se].forEach(m => scopes.push([y + '|' + se + '|' + m, rs.filter(r => r.month === m)]));
    }));
    const N = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
    const out = [];
    scopes.forEach(([scope, rs]) => {
      for (let i = 0; i < 7; i++) {
        const wr = rs.filter(r => r.weekday === i); const per = {}; wr.forEach(r => { per[r.date] = (per[r.date] || 0) + 1; });
        const c = Object.values(per);
        out.push(mix({ key: scope + '|' + i, scope, weekday: N[i], n: wr.length, days: c.length }, cnt(c), dur(wr)));
      }
    });
    return out;
  },
});

dash.calc('scope_bins', {
  inputs: ['restrictions'],
  title: 'Продолжительность по периодам',
  description: 'Число ограничений по интервалам продолжительности в каждом периоде.',
  fn: (restrictions) => {
    const SM = { 'Зима': [1, 2, 12], 'Весна': [3, 4, 5], 'Лето': [6, 7, 8], 'Осень': [9, 10, 11] };
    const scopes = [['all', restrictions]];
    window.MR_YEARS.forEach(y => Object.keys(SM).forEach(se => {
      const rs = restrictions.filter(r => r.year === y && r.season === se);
      scopes.push([y + '|' + se, rs]);
      SM[se].forEach(m => scopes.push([y + '|' + se + '|' + m, rs.filter(r => r.month === m)]));
    }));
    const B = [[0, 30, 'до 30 мин'], [30, 60, '30–60 мин'], [60, 120, '1–2 ч'], [120, 240, '2–4 ч'], [240, 480, '4–8 ч'], [480, 1440, '8–24 ч']];
    const out = [];
    scopes.forEach(([scope, rs]) => {
      const d = rs.map(r => r.duration_min).filter(v => v != null);
      B.forEach(([a, b, bin]) => { const n = d.filter(v => (a === 0 ? v >= 0 : v > a) && v <= b).length; out.push({ key: scope + '|' + bin, scope, bin, n, share: d.length ? Math.round(1000 * n / d.length) / 10 : 0 }); });
    });
    return out;
  },
});

dash.calc('scope_sum', {
  inputs: ['restrictions'],
  title: 'Итоги периода',
  description: 'Для каждого периода: введений, дней, число введений за день (среднее, медиана, мин, макс), продолжительность в минутах (среднее, медиана, мин, макс), самый частый час.',
  fn: (restrictions) => {
    const R1 = (v) => v == null ? null : Math.round(v * 10) / 10;
    const med = (s) => { if (!s.length) return null; const a = [...s].sort((x, y) => x - y), k = a.length; return k % 2 ? a[(k - 1) / 2] : (a[k / 2 - 1] + a[k / 2]) / 2; };
    const cnt = (c) => ({ mean: c.length ? Math.round(100 * c.reduce((a, b) => a + b, 0) / c.length) / 100 : 0, median: c.length ? med(c) : 0, min: c.length ? Math.min(...c) : 0, max: c.length ? Math.max(...c) : 0 });
    const mix = (a, b, c) => { for (const k in b) a[k] = b[k]; for (const k in c) a[k] = c[k]; return a; };
    const dur = (rs) => { const d = rs.map(r => r.duration_min).filter(v => v != null); return { d_n: d.length, d_mean: d.length ? R1(d.reduce((a, b) => a + b, 0) / d.length) : null, d_median: R1(med(d)), d_min: d.length ? R1(Math.min(...d)) : null, d_max: d.length ? R1(Math.max(...d)) : null }; };
    const SM = { 'Зима': [1, 2, 12], 'Весна': [3, 4, 5], 'Лето': [6, 7, 8], 'Осень': [9, 10, 11] };
    const scopes = [['all', restrictions]];
    window.MR_YEARS.forEach(y => Object.keys(SM).forEach(se => {
      const rs = restrictions.filter(r => r.year === y && r.season === se);
      scopes.push([y + '|' + se, rs]);
      SM[se].forEach(m => scopes.push([y + '|' + se + '|' + m, rs.filter(r => r.month === m)]));
    }));
    const p = (n) => String(n).padStart(2, '0');
    const r0 = (v) => v == null ? null : Math.round(v);
    return scopes.map(([scope, rs]) => {
      const hc = new Array(24).fill(0); rs.forEach(r => { if (r.hour != null) hc[r.hour]++; });
      const ph = hc.indexOf(Math.max(...hc));
      const per = {}; rs.forEach(r => { per[r.date] = (per[r.date] || 0) + 1; });
      const c = cnt(Object.values(per)); const d = dur(rs);
      return { scope, n: rs.length, days: Object.keys(per).length,
        day_mean: c.mean, day_median: c.median, day_min: c.min, day_max: c.max,
        dur_n: d.d_n, mean_dur: r0(d.d_mean), median_dur: r0(d.d_median), min_dur: r0(d.d_min), max_dur: r0(d.d_max),
        peak_hour_label: rs.length ? p(ph) + ':00–' + p((ph + 1) % 24) + ':00' : null };
    });
  },
});

dash.calc('monthly', {
  inputs: ['restrictions'],
  title: 'Месяцы по сезонам',
  description: 'Для каждого месяца сезона: всего введений, дней, среднее, медиана, минимум и максимум за день; статистика продолжительности (мин).',
  fn: (restrictions) => {
    const R1 = (v) => v == null ? null : Math.round(v * 10) / 10;
    const med = (s) => { if (!s.length) return null; const a = [...s].sort((x, y) => x - y), k = a.length; return k % 2 ? a[(k - 1) / 2] : (a[k / 2 - 1] + a[k / 2]) / 2; };
    const cnt = (c) => ({ mean: c.length ? Math.round(100 * c.reduce((a, b) => a + b, 0) / c.length) / 100 : 0, median: c.length ? med(c) : 0, min: c.length ? Math.min(...c) : 0, max: c.length ? Math.max(...c) : 0 });
    const mix = (a, b, c) => { for (const k in b) a[k] = b[k]; for (const k in c) a[k] = c[k]; return a; };
    const dur = (rs) => { const d = rs.map(r => r.duration_min).filter(v => v != null); return { d_n: d.length, d_mean: d.length ? R1(d.reduce((a, b) => a + b, 0) / d.length) : null, d_median: R1(med(d)), d_min: d.length ? R1(Math.min(...d)) : null, d_max: d.length ? R1(Math.max(...d)) : null }; };
    const SM = { 'Зима': [1, 2, 12], 'Весна': [3, 4, 5], 'Лето': [6, 7, 8], 'Осень': [9, 10, 11] };
    const out = [];
    window.MR_YEARS.forEach(year => Object.keys(SM).forEach(season => SM[season].forEach(month => {
      const rs = restrictions.filter(r => r.year === year && r.month === month);
      const per = {}; rs.forEach(r => { per[r.date] = (per[r.date] || 0) + 1; });
      const c = Object.values(per);
      out.push(mix({ key: year + '|' + season + '|' + month, year, season, month, total: rs.length, days: c.length }, cnt(c), dur(rs)));
    })));
    return out;
  },
});

dash.calc('dur_season', {
  inputs: ['restrictions'],
  title: 'Продолжительность по сезонам',
  description: 'Минимум, квартили, медиана, среднее и максимум продолжительности (мин) в каждом сезоне.',
  fn: (restrictions) => {
    const q = (s, p) => { if (!s.length) return null; const i = (s.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i); return s[lo] + (s[hi] - s[lo]) * (i - lo); };
    const out = [];
    window.MR_YEARS.forEach(year => ['Зима','Весна','Лето','Осень'].forEach(season => {
      const s = restrictions.filter(r => r.year === year && r.season === season && r.duration_min != null).map(r => r.duration_min).sort((a, b) => a - b);
      const r1 = (v) => v == null ? null : Math.round(v * 10) / 10;
      out.push({ key: year + '|' + season, year, season, n: s.length, min: r1(q(s, 0)), q1: r1(q(s, .25)), median: r1(q(s, .5)), q3: r1(q(s, .75)), max: r1(q(s, 1)),
        mean: s.length ? r1(s.reduce((a, b) => a + b, 0) / s.length) : null });
    }));
    return out;
  },
});

// ---------- shared chart helper ----------
const MR = (() => {
  const MS = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
  const MF = ['январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь'];
  const fmtN = d3.format(',');
  const fmtD = (m) => m == null ? '—' : (m < 60 ? Math.round(m) + ' мин' : Math.floor(m / 60) + ' ч ' + String(Math.round(m % 60)).padStart(2, '0') + ' мин');
  const p2 = (n) => String(n).padStart(2, '0');

  function chart(el, items, o) {
    el.replaceChildren();
    const W = Math.max(260, el.clientWidth || 600);
    const H = o.height || 240;
    const mt = o.notes ? 34 : 12, mr = 8, mb = o.groups ? 42 : 24;
    const svg = d3.select(el).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`);
    const top = (d) => o.box ? (d.max ?? 0) : (d.max ?? d.mean ?? 0);
    const ymax = Math.max(d3.max(items, top) || 0, o.minMax || 1);
    const y = d3.scaleLinear([0, ymax * 1.05], [H - mb, mt]).nice();
    const fy = o.fmtY || fmtN;
    const ticks = y.ticks(4);
    let ml = 0;
    const meas = svg.append('g');
    ticks.forEach(t => { ml = Math.max(ml, meas.append('text').text(fy(t)).node().getComputedTextLength()); });
    meas.remove(); ml = Math.ceil(ml) + 10;
    const x = d3.scaleBand(items.map((d, i) => i), [ml, W - mr]).padding(o.pad ?? 0.25);
    const bw = Math.min(32, x.bandwidth());
    const cx = (i) => x(i) + x.bandwidth() / 2;
    const gy = svg.append('g');
    ticks.forEach(t => {
      gy.append('line').attr('x1', ml).attr('x2', W - mr).attr('y1', y(t)).attr('y2', y(t)).attr('stroke', 'var(--cds-chart-grid)');
      gy.append('text').attr('x', ml - 6).attr('y', y(t)).attr('dy', '0.32em').attr('text-anchor', 'end').text(fy(t));
    });
    svg.append('line').attr('x1', ml).attr('x2', W - mr).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', 'var(--cds-chart-axis)');
    const g = svg.append('g');
    items.forEach((d, i) => {
      const c = cx(i);
      if (o.box) {
        if (!d.n) return;
        g.append('line').attr('x1', c).attr('x2', c).attr('y1', y(d.min)).attr('y2', y(d.max)).attr('stroke', 'var(--color-fg)').attr('stroke-width', 1.5);
        [d.min, d.max].forEach(v => g.append('line').attr('x1', c - bw * .25).attr('x2', c + bw * .25).attr('y1', y(v)).attr('y2', y(v)).attr('stroke', 'var(--color-fg)').attr('stroke-width', 1.5));
        g.append('rect').attr('x', c - bw / 2).attr('width', bw).attr('y', y(d.q3)).attr('height', Math.max(1.5, y(d.q1) - y(d.q3))).attr('rx', 2).attr('fill', dash.colors[0]).attr('fill-opacity', .85);
        g.append('line').attr('x1', c - bw / 2).attr('x2', c + bw / 2).attr('y1', y(d.median)).attr('y2', y(d.median)).attr('stroke', 'var(--color-bg)').attr('stroke-width', 2);
        g.append('circle').attr('cx', c).attr('cy', y(d.mean)).attr('r', 2.6).attr('fill', 'var(--color-fg)');
      } else {
        const v = d.mean ?? 0;
        if (v > 0) g.append('rect').attr('x', c - bw / 2).attr('width', bw).attr('y', y(v)).attr('height', y(0) - y(v)).attr('rx', 2).attr('fill', d.muted ? 'var(--cds-chart-muted)' : (o.color || dash.colors[0])).attr('fill-opacity', .85);
        if (d.max != null && d.max > 0) {
          g.append('line').attr('x1', c).attr('x2', c).attr('y1', y(d.min)).attr('y2', y(d.max)).attr('stroke', 'var(--color-fg)').attr('stroke-width', 1.5);
          [d.min, d.max].forEach(vv => g.append('line').attr('x1', c - bw * .3).attr('x2', c + bw * .3).attr('y1', y(vv)).attr('y2', y(vv)).attr('stroke', 'var(--color-fg)').attr('stroke-width', 1.5));
        }

      }
      if (o.notes && d.note) g.append('text').attr('class', 'ann').attr('x', c).attr('y', y(top(d)) - 8).attr('text-anchor', 'middle').text(d.note);
    });
    // x labels
    const step = o.step ? o.step(x.bandwidth()) : 1;
    items.forEach((d, i) => {
      if (d.label == null || (i % step && !d.force)) return;
      svg.append('text').attr('x', cx(i)).attr('y', H - mb + 15).attr('text-anchor', 'middle').text(d.label);
    });
    (o.groups || []).forEach(gr => {
      const a = x(gr.from), b = x(gr.to) + x.bandwidth();
      svg.append('text').attr('x', (a + b) / 2).attr('y', H - 6).attr('text-anchor', 'middle').attr('class', 'ann').text(gr.label);
      if (gr.from > 0) svg.append('line').attr('x1', a - x.step() * x.paddingInner() / 2).attr('x2', a - x.step() * x.paddingInner() / 2).attr('y1', mt).attr('y2', H - 4).attr('stroke', 'var(--cds-chart-grid)');
    });
    // tooltip
    const tip = document.createElement('div'); tip.className = 'tip'; tip.hidden = true; el.appendChild(tip);
    const hl = svg.append('rect').attr('fill', 'var(--color-fg)').attr('fill-opacity', .06).attr('pointer-events', 'none').attr('visibility', 'hidden');
    items.forEach((d, i) => {
      svg.append('rect').attr('x', x(i) - x.step() * x.paddingInner() / 2).attr('width', x.step()).attr('y', mt).attr('height', H - mb - mt).attr('fill', 'transparent')
        .on('mouseenter', () => {
          hl.attr('x', x(i) - x.step() * x.paddingInner() / 2).attr('width', x.step()).attr('y', mt).attr('height', H - mb - mt).attr('visibility', 'visible');
          tip.replaceChildren();
          d.tip.forEach((line, k) => { const div = document.createElement('div'); if (!k) div.className = 't0'; div.textContent = line; tip.appendChild(div); });
          tip.hidden = false;
          const scale = el.clientWidth / W;
          let left = cx(i) * scale + 10; const tw = tip.offsetWidth;
          if (left + tw > el.clientWidth) left = Math.max(0, cx(i) * scale - tw - 10);
          tip.style.left = left + 'px'; tip.style.top = Math.max(0, mt * scale) + 'px';
        })
        .on('mouseleave', () => { tip.hidden = true; hl.attr('visibility', 'hidden'); });
    });
  }
  return { chart, MS, MF, fmtN, fmtD, p2 };
})();
window.MR = MR;

// ---------- controls ----------
const scopeKey = () => { const p = dash.params(); if (p.all) return 'all'; return p.year + '|' + p.season + (p.month ? '|' + p.month : ''); };
document.querySelectorAll('.mr-stat').forEach(b => b.addEventListener('click', () => dash.setParams({ stat: b.dataset.stat })));
document.querySelectorAll('.mr-metric').forEach(b => b.addEventListener('click', () => dash.setParams({ metric: b.dataset.metric })));
document.querySelectorAll('.mr-all').forEach(b => b.addEventListener('click', () => dash.setParams({ all: b.dataset.all === '1' })));
document.querySelectorAll('.mr-year').forEach(b => b.addEventListener('click', () => dash.setParams({ year: +b.dataset.year })));
document.querySelectorAll('.mr-season').forEach(b => b.addEventListener('click', () => dash.setParams({ season: b.dataset.season, month: null })));
document.querySelectorAll('.mr-month').forEach(b => b.addEventListener('click', () => dash.setParams({ month: +b.dataset.month || null })));
dash.onData(() => {
  const p = dash.params(); const all = !!p.all; const isDur = p.metric === 'duration';
  document.querySelectorAll('.mr-metric').forEach(b => b.setAttribute('aria-pressed', String((b.dataset.metric === 'duration') === isDur)));
  const isMed = p.stat === 'median';
  document.querySelectorAll('.mr-stat').forEach(b => b.setAttribute('aria-pressed', String((b.dataset.stat === 'median') === isMed)));
  document.querySelectorAll('.mr-st-mean').forEach(e => { e.hidden = isMed; });
  document.querySelectorAll('.mr-st-med').forEach(e => { e.hidden = !isMed; });
  document.querySelectorAll('.mr-mc').forEach(e => { e.hidden = isDur; });
  document.querySelectorAll('.mr-md').forEach(e => { e.hidden = !isDur; });
  document.querySelectorAll('.mr-all').forEach(b => b.setAttribute('aria-pressed', String((b.dataset.all === '1') === all)));
  document.querySelectorAll('.mr-year').forEach(b => { b.setAttribute('aria-pressed', String(!all && +b.dataset.year === +p.year)); b.disabled = all; });
  document.querySelectorAll('.mr-season').forEach(b => { b.setAttribute('aria-pressed', String(!all && b.dataset.season === p.season)); b.disabled = all; });
  document.querySelectorAll('.mr-month').forEach(b => {
    b.hidden = !(b.dataset.seasonof === '*' || b.dataset.seasonof === p.season);
    b.setAttribute('aria-pressed', String(!all && (+b.dataset.month || null) === (p.month || null)));
    b.disabled = all;
  });
  const s = dash.data('scope_sum');
  const row = s.status === 'ok' ? s.data.find(r => r.scope === scopeKey()) : null;
  const has = !row || row.n > 0;
  document.querySelectorAll('.mr-sum-has').forEach(e => { e.hidden = !has; });
  document.querySelectorAll('.mr-sum-none').forEach(e => { e.hidden = has; });
});

// ---------- drawings ----------
const safe = (fn) => (el) => { try { fn(el); } catch (e) { el.replaceChildren(); el.textContent = '—'; console.error(e); } };
const one = (id, field) => { const r = dash.data(id); return r.status === 'ok' && r.data.length ? r.data[0][field] : null; };
const put = (el, v) => { el.textContent = v == null ? '—' : String(v); };
dash.draw('k-total', el => { const v = one('kpi', 'total'); put(el, v == null ? null : MR.fmtN(v)); });
dash.draw('k-days', el => put(el, one('kpi', 'days')));
dash.draw('k-med', el => put(el, one('kpi', 'median_dur')));
dash.draw('k-med2', el => put(el, one('kpi', 'median_dur')));
dash.draw('k-night', el => put(el, one('kpi', 'night_pct')));
dash.draw('k-peak', el => put(el, one('kpi', 'peak_hour_label')));
dash.draw('k-topm', el => put(el, one('kpi', 'top_month_label')));

const scopeRows = (id) => { const r = dash.data(id); return r.status === 'ok' ? r.data.filter(d => d.scope === scopeKey()) : null; };
dash.draw('sel-label', el => {
  const p = dash.params();
  el.textContent = p.all ? 'всё время' : p.month ? MR.MF[p.month - 1] + ' ' + p.year : (p.season || '').toLowerCase() + ' ' + p.year;
});
['n', 'days', 'peak_hour_label', 'median_dur'].forEach((f, i) => {
  dash.draw(['s-n', 's-days', 's-peak', 's-med'][i], el => {
    el.setAttribute('data-where', 'scope=' + scopeKey());
    const rows = scopeRows('scope_sum'); put(el, rows && rows[0] ? rows[0][f] : null);
  });
});

[['st-dmean', 'day_mean'], ['st-dmed', 'day_median'], ['st-dmin', 'day_min'], ['st-dmax', 'day_max'], ['st-n', 'n'],
 ['st-mean', 'mean_dur'], ['st-med', 'median_dur'], ['st-min', 'min_dur'], ['st-max', 'max_dur'], ['st-dn', 'dur_n']].forEach(([name, f]) => {
  dash.draw(name, el => {
    el.setAttribute('data-where', 'scope=' + scopeKey());
    const rows = scopeRows('scope_sum'); put(el, rows && rows[0] ? rows[0][f] : null);
  });
});

// count or duration items for a candle
const isDur = () => dash.params().metric === 'duration';
const h60 = (v) => v == null ? null : v / 60;
const isMed = () => dash.params().stat === 'median';
const mix2 = (a, b) => { for (const k in b) a[k] = b[k]; return a; };
const candle = (d) => isDur() ? { mean: h60(isMed() ? d.d_median : d.d_mean), min: h60(d.d_min), max: h60(d.d_max) } : { mean: isMed() ? d.median : d.mean, min: d.min, max: d.max };
const durTip = (d) => d.d_n ? ['ограничений с известной продолжительностью: ' + d.d_n, 'среднее: ' + MR.fmtD(d.d_mean), 'медиана: ' + MR.fmtD(d.d_median), 'мин / макс: ' + MR.fmtD(d.d_min) + ' / ' + MR.fmtD(d.d_max)] : ['нет данных о продолжительности'];
const cntTip = (d, n) => ['всего введений: ' + n + ' за ' + d.days + ' дн.', 'в среднем за день: ' + d3.format('.2f')(d.mean), 'медиана за день: ' + d.median, 'мин / макс за день: ' + d.min + ' / ' + d.max];
const yOpt = () => isDur() ? { fmtY: v => d3.format('~g')(v) + ' ч' } : { fmtY: d3.format('~g') };

dash.draw('months-all', safe(el => {
  const r = dash.data('months_all');
  if (r.status !== 'ok') { el.textContent = '—'; return; }
  const items = r.data.map(d => ({ mean: d.n, label: d.month === 1 ? MR.MS[0] + ' ’' + String(d.year).slice(2) : d.month === 7 ? MR.MS[6] : null, force: true,
    tip: [MR.MF[d.month - 1] + ' ' + d.year, 'введений: ' + MR.fmtN(d.n), 'дней с ограничениями: ' + d.days].concat(d.ym < window.MR_FIRST_MONTH ? ['канал ещё не существовал'] : []) }));
  MR.chart(el, items, { height: 240, pad: 0.15 });
}));

dash.draw('season-hours', safe(el => {
  const rows = scopeRows('scope_hours');
  if (!rows) { el.textContent = '—'; return; }
  const items = rows.sort((a, b) => a.hour - b.hour).map(d => mix2(candle(d), { label: MR.p2(d.hour),
    tip: [MR.p2(d.hour) + ':00–' + MR.p2((d.hour + 1) % 24) + ':00'].concat(isDur() ? durTip(d) : cntTip(d, d.n)) }));
  MR.chart(el, items, mix2({ height: 280, step: bw => bw < 16 ? 3 : bw < 24 ? 2 : 1 }, yOpt()));
}));

dash.draw('hours-all', safe(el => {
  const rows = scopeRows('scope_hours');
  if (!rows) { el.textContent = '—'; return; }
  const items = rows.sort((a, b) => a.hour - b.hour).map(d => ({ mean: d.n, label: MR.p2(d.hour), tip: [MR.p2(d.hour) + ':00–' + MR.p2((d.hour + 1) % 24) + ':00', 'введений: ' + MR.fmtN(d.n)] }));
  MR.chart(el, items, { height: 240, step: bw => bw < 16 ? 3 : bw < 24 ? 2 : 1 });
}));

dash.draw('hours-dur', safe(el => {
  const rows = scopeRows('scope_hours');
  if (!rows) { el.textContent = '—'; return; }
  const med = isMed();
  const items = rows.sort((a, b) => a.hour - b.hour).map(d => ({ mean: h60(med ? d.d_median : d.d_mean), label: MR.p2(d.hour),
    tip: [MR.p2(d.hour) + ':00–' + MR.p2((d.hour + 1) % 24) + ':00'].concat(durTip(d)) }));
  MR.chart(el, items, { height: 240, color: dash.colors[1], fmtY: v => d3.format('~g')(v) + ' ч', step: bw => bw < 16 ? 3 : bw < 24 ? 2 : 1 });
}));

dash.draw('weekdays', safe(el => {
  const rows = scopeRows('scope_weekdays');
  if (!rows) { el.textContent = '—'; return; }
  MR.chart(el, rows.map(d => mix2(candle(d), { label: d.weekday, tip: [d.weekday].concat(isDur() ? durTip(d) : cntTip(d, d.n)) })), mix2({ height: 240 }, yOpt()));
}));

dash.draw('dur-bins', safe(el => {
  const rows = scopeRows('scope_bins');
  if (!rows) { el.textContent = '—'; return; }
  MR.chart(el, rows.map(d => ({ mean: d.n, label: d.bin, tip: [d.bin, 'ограничений: ' + MR.fmtN(d.n), 'доля: ' + d.share + '%'] })), { height: 240, color: dash.colors[1], step: bw => bw < 60 ? 2 : 1 });
}));

dash.draw('top-days', tb => {
  const r = dash.data('top_days');
  tb.replaceChildren();
  if (r.status !== 'ok') return;
  r.data.forEach(d => {
    const tr = document.createElement('tr');
    [['date', ''], ['weekday_name', ''], ['n', 'num'], ['airports', '']].forEach(([f, c]) => { const td = document.createElement('td'); td.textContent = String(d[f]); if (c) td.className = c; tr.appendChild(td); });
    tb.appendChild(tr);
  });
});

dash.draw('season-months', safe(el => {
  const p = dash.params();
  if (p.all) {
    const r = dash.data('months_all');
    if (r.status !== 'ok') { el.textContent = '—'; return; }
    const items = r.data.map(d => mix2(candle(d), { label: d.month === 1 ? MR.MS[0] + ' ’' + String(d.year).slice(2) : d.month === 7 ? MR.MS[6] : null, force: true,
      tip: [MR.MF[d.month - 1] + ' ' + d.year].concat(isDur() ? durTip(d) : cntTip(d, d.n)) }));
    MR.chart(el, items, mix2({ height: 280, pad: 0.15 }, yOpt()));
    return;
  }
  const r = dash.data('monthly');
  if (r.status !== 'ok') { el.textContent = '—'; return; }
  const rows = r.data.filter(d => d.year === +p.year && d.season === p.season);
  const items = rows.map(d => mix2(candle(d), { label: MR.MF[d.month - 1] + ' ' + d.year, muted: !!p.month && d.month !== +p.month,
    note: isDur() ? (d.d_n ? (isMed() ? 'медиана ' + MR.fmtD(d.d_median) : 'среднее ' + MR.fmtD(d.d_mean)) : '') : d.total + ' огр. · ' + d.days + ' дн.',
    tip: [MR.MF[d.month - 1] + ' ' + d.year].concat(isDur() ? durTip(d) : cntTip(d, d.total)) }));
  MR.chart(el, items, mix2({ height: 280, notes: true, pad: 0.4 }, yOpt()));
}));

dash.draw('dur-season', safe(el => {
  const r = dash.data('dur_season');
  if (r.status !== 'ok') { el.textContent = '—'; return; }
  const SI = { 'Зима': 'З', 'Весна': 'В', 'Лето': 'Л', 'Осень': 'О' };
  const h = (v) => v == null ? null : v / 60;
  const items = r.data.map(d => ({ box: true, n: d.n, min: h(d.min), q1: h(d.q1), median: h(d.median), q3: h(d.q3), max: h(d.max), mean: h(d.mean), label: SI[d.season],
    tip: d.n ? [d.season + ' ' + d.year, 'ограничений с известной длительностью: ' + d.n, 'медиана: ' + MR.fmtD(d.median), 'среднее: ' + MR.fmtD(d.mean), '25–75%: ' + MR.fmtD(d.q1) + ' – ' + MR.fmtD(d.q3), 'мин / макс: ' + MR.fmtD(d.min) + ' / ' + MR.fmtD(d.max)]
                : [d.season + ' ' + d.year, 'нет данных'] }));
  const groups = window.MR_YEARS.map(y => ({ label: String(y), from: r.data.findIndex(d => d.year === y), to: r.data.length - 1 - [...r.data].reverse().findIndex(d => d.year === y) }));
  MR.chart(el, items, { height: 300, box: true, groups, fmtY: v => d3.format('~g')(v) + ' ч', pad: 0.3 });
}));
</script>
'''


# ---------------------------------------------------------------- HTML
SHELL = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ограничения в аэропортах Москвы __YEAR_RANGE__</title>
<style>
:root{
  color-scheme: light;
  --font-anthropic-sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-anthropic-serif: Georgia, "Times New Roman", serif;
  --color-bg:#faf9f5; --color-panel:#ffffff; --color-fg:#1f1e1d; --color-fg-muted:#6b6a65; --color-border-line:#e5e3dc;
  --cds-chart-grid:#ecebe5; --cds-chart-axis:#b9b7ae; --cds-chart-muted:#cfcdc5;
  --cds-surface-popover:#ffffff; --cds-border:#dedcd4; --cds-shadow-popover:0 4px 16px rgba(0,0,0,.12); --cds-text-secondary:#6b6a65;
  --cds-font-size-caption:12px; --cds-font-size-body:14px; --cds-font-size-heading:16px; --cds-font-size-title:30px; --cds-font-weight-medium:600;
  --cds-gap-xs:4px; --cds-gap-sm:8px; --cds-gap-md:16px; --cds-gap-lg:24px; --cds-gap-xl:40px;
  --cds-pad-xs:4px; --cds-pad-sm:8px; --cds-pad-md:12px; --cds-pad-lg:20px; --cds-radius:8px; --cds-dur-slow:300ms;
  --c1:#c96442; --c2:#4a7fb0; --c3:#5f9a5a;
}
@media (prefers-color-scheme: dark){
  :root{
    color-scheme: dark;
    --color-bg:#1f1e1d; --color-panel:#2a2927; --color-fg:#f0eee6; --color-fg-muted:#a8a69e; --color-border-line:#3d3b37;
    --cds-chart-grid:#353431; --cds-chart-axis:#6b6a65; --cds-chart-muted:#55534e;
    --cds-surface-popover:#2f2e2b; --cds-border:#45433e; --cds-shadow-popover:0 4px 16px rgba(0,0,0,.5); --cds-text-secondary:#a8a69e;
    --c1:#e07a55; --c2:#6fa0d0; --c3:#7fbf78;
  }
}
html,body{margin:0;background:var(--color-bg);color:var(--color-fg)}
#dash-root{padding:clamp(16px,4vw,48px);max-width:1400px;margin:0 auto;box-sizing:border-box}
.mr-footer{margin-top:24px;font:12px var(--font-anthropic-sans);color:var(--color-fg-muted)}
</style>
__D3__
<script>
window.MR_YEARS = __YEARS__;
window.MR_FIRST_MONTH = __FIRST_MONTH__;
// Небольшая замена среды дашборда: расчёты (calc), отрисовки (draw) и фильтры (params).
window.dash = (function () {
  const DATA = __DATA__;
  const DEFAULTS = __PARAMS__;
  const sources = { restrictions: { status: 'ok', data: DATA, columns: DATA.length ? Object.keys(DATA[0]) : [] } };
  const calcs = {}, cache = {}, draws = {}, ons = [];
  let params = Object.assign({}, DEFAULTS), started = false;
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  function data(id) {
    if (sources[id]) return sources[id];
    const c = calcs[id];
    if (!c) return { status: 'missing', data: [] };
    if (!cache[id]) {
      try { cache[id] = { status: 'ok', data: c.fn.apply(null, c.inputs.map((i) => data(i).data)) }; }
      catch (e) { console.error('calc ' + id, e); cache[id] = { status: 'error', data: [], message: String(e) }; }
    }
    return cache[id];
  }
  function render() {
    if (!started) return;
    ons.forEach((f) => { try { f(); } catch (e) { console.error(e); } });
    Object.keys(draws).forEach((n) => document.querySelectorAll('[data-draw="' + n + '"]').forEach((el) => {
      if (el.closest('[hidden]')) return;
      try { draws[n](el); } catch (e) { console.error('draw ' + n, e); }
    }));
  }
  return {
    calc(id, o) { calcs[id] = o; },
    data,
    draw(n, f) { if (typeof f === 'function') draws[n] = f; else render(); },
    onData(f) { ons.push(f); if (started) f(); },
    params() { return params; },
    setParams(p) { for (const k in p) { if (p[k] == null) delete params[k]; else params[k] = p[k]; } render(); },
    resetParams() { params = Object.assign({}, DEFAULTS); render(); },
    setLink() {}, refresh() {}, loader() {},
    get colors() { return [css('--c1'), css('--c2'), css('--c3')]; },
    _start() {
      started = true; render();
      let t; window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(render, 150); });
      if (window.matchMedia) matchMedia('(prefers-color-scheme: dark)').addEventListener('change', render);
    },
  };
})();
</script>
</head>
<body>
<div id="dash-root">
__BODY__
<p class="mr-footer">Сгенерировано __GENERATED__ из файла __SOURCE__ · __N__ ограничений.</p>
</div>
<script>dash._start();</script>
</body>
</html>
'''

D3_CDN = '<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>'


def js(obj):
    return json.dumps(obj, ensure_ascii=False).replace('</', '<\\/')


def render_html(rows, first_msg, last_msg, source_name, d3_path=None):
    years = list(range(min(first_msg.year, min(r['year'] for r in rows)), max(r['year'] for r in rows) + 1))
    last = max(rows, key=lambda r: r['date'])
    defaults = {'year': last['year'], 'season': last['season'], 'all': False, 'metric': 'count', 'stat': 'mean'}
    first_r = min(rows, key=lambda r: r['date'])
    fr = dt.date.fromisoformat(first_r['date'])
    year_buttons = ''.join(f'<button type="button" class="mr-year" data-year="{y}">{y}</button>' for y in years)
    if first_msg.month == 1 and first_msg.day == 1:
        export_note = f'Выгрузка канала начинается {ru_date(first_msg)}.'
    else:
        export_note = (f'Выгрузка канала начинается {ru_date(first_msg)}, поэтому за месяцы '
                       f'до {MONTH_GEN[first_msg.month - 1]} {first_msg.year} сообщений нет.')
    method_note = (f'Годы считаются с января {years[0]}; выгрузка начинается {ru_date(first_msg)}, '
                   f'первое найденное ограничение в Москве — {ru_date(fr)}. До мая 2025 канал публиковал '
                   f'в основном итоговые сообщения, поэтому ранние годы представлены редкими эпизодами.')
    period = f'{MONTH_NOM[fr.month - 1]} {fr.year} — {ru_date(last_msg)}'
    body = (TEMPLATE_BODY
            .replace('__PERIOD__', period)
            .replace('__FIRST_YEAR__', str(years[0]))
            .replace('__EXPORT_NOTE__', export_note)
            .replace('__YEAR_BUTTONS__', year_buttons)
            .replace('__METHOD_NOTE__', method_note))
    if d3_path:
        d3_tag = '<script>' + Path(d3_path).read_text(encoding='utf-8').replace('</script', '<\\/script') + '</script>'
    else:
        d3_tag = D3_CDN
    return (SHELL
            .replace('__D3__', d3_tag)
            .replace('__YEAR_RANGE__', f'{years[0]}–{years[-1]}')
            .replace('__YEARS__', js(years))
            .replace('__FIRST_MONTH__', js(first_msg.strftime('%Y-%m')))
            .replace('__PARAMS__', js(defaults))
            .replace('__GENERATED__', dt.datetime.now().strftime('%d.%m.%Y %H:%M'))
            .replace('__SOURCE__', Path(source_name).name)
            .replace('__N__', str(len(rows)))
            .replace('__DATA__', js(rows))
            .replace('__BODY__', body))


# ---------------------------------------------------------------- запуск
def run(input_path, output_path='moscow_restrictions_dashboard.html', csv_path=None, json_path=None,
        d3_path=None, auto_from='2025-05-01', gap_hours=6, max_hours=24, verbose=True):
    """Разбирает экспорт и пишет дашборд. Возвращает (строки ограничений, HTML).
    Удобно вызывать из Jupyter / Google Colab."""
    raw = json.loads(Path(input_path).read_text(encoding='utf-8'))
    messages = raw['messages'] if isinstance(raw, dict) else raw
    dated = [dt.datetime.fromisoformat(m['date']) for m in messages if m.get('date')]
    if not dated:
        raise ValueError('В файле нет сообщений с датами.')
    first_msg, last_msg = min(dated), max(dated)
    start = dt.datetime.fromisoformat(auto_from)

    events = extract_events(messages, start)
    episodes, orphan = build_episodes(events, gap_hours, max_hours)
    episodes += early_episodes(first_msg, start)
    rows = to_rows(episodes)
    if not rows:
        raise ValueError('Ограничений в московских аэропортах не найдено — дашборд не построен.')

    if verbose:
        print_summary(rows, orphan)
    html = render_html(rows, first_msg, last_msg, input_path, d3_path)
    if output_path:
        Path(output_path).write_text(html, encoding='utf-8')
        if verbose:
            print(f'Дашборд: {output_path}')
    if csv_path:
        import csv
        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        if verbose:
            print(f'CSV: {csv_path}')
    if json_path:
        Path(json_path).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
        if verbose:
            print(f'JSON: {json_path}')
    return rows, html


def main():
    ap = argparse.ArgumentParser(description='Дашборд ограничений в аэропортах Москвы по экспорту канала «Говорит Росавиация».')
    ap.add_argument('input', help='JSON-экспорт канала из Telegram Desktop (result.json)')
    ap.add_argument('-o', '--output', default='moscow_restrictions_dashboard.html', help='куда записать HTML')
    ap.add_argument('--csv', help='дополнительно сохранить таблицу ограничений в CSV')
    ap.add_argument('--json-out', help='дополнительно сохранить таблицу ограничений в JSON')
    ap.add_argument('--d3', help='путь к d3.v7.min.js, чтобы встроить библиотеку и открывать файл без интернета')
    ap.add_argument('--auto-from', default='2025-05-01',
                    help='с какой даты разбирать сообщения автоматически (до неё — разобранные вручную сводки)')
    ap.add_argument('--gap-hours', type=float, default=6,
                    help='новое введение спустя столько часов без снятия считается новым ограничением')
    ap.add_argument('--max-hours', type=float, default=24,
                    help='продолжительность длиннее этого не считается (снятие не опубликовано)')
    a = ap.parse_args()
    try:
        run(a.input, a.output, a.csv, a.json_out, a.d3, a.auto_from, a.gap_hours, a.max_hours)
    except ValueError as e:
        sys.exit(str(e))


if __name__ == '__main__':
    main()
