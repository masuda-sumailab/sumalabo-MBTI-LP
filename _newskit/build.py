#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""賃貸物件ニュースを組み立てる道具(これ1本で動く。ほかの道具箱はいらない)。

  python3 _newskit/build.py          切り抜き帳(_newskit/ledger.json)から news/ のページを作り直し、sitemap.xml のニュース部分を書き換える
  python3 _newskit/build.py --check  ページは作らず、切り抜き帳の書き方だけ確かめる

書き方の決まりと毎朝の手順は _newskit/README.md。
このフォルダ(_newskit)は .vercelignore でサイトには出さない。ページの外枠は shell.html、猫の絵は news/img/。"""
import io, os, re, sys, json, datetime, html as _h

KIT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(KIT)
CHECK_ONLY = '--check' in sys.argv


def rd(p): return io.open(p, encoding='utf-8').read()
def wr(p, s): io.open(p, 'w', encoding='utf-8', newline='\n').write(s)


L = json.loads(rd(os.path.join(KIT, 'ledger.json')))
ST = L['settings']
SITE, LINE_URL, SUUMO_DATE, BANNED = ST['site'], ST['line_url'], ST['suumo_date'], ST['banned']
SERIES, TAGLINE, TH = L['series']['name'], L['series']['tagline'], L['themes']
ITEMS = sorted(L['items'], key=lambda x: (x['issue'], x['id']), reverse=True)
ISSUES = sorted({x['issue'] for x in ITEMS}, reverse=True)
SHELL = rd(os.path.join(KIT, 'shell.html'))
WD = '月火水木金土日'
KINDS = ('役所の発表', '会社の発表', '団体の発表', '報道')
IMG = ['shocho-shiraberu.png', 'shocho-point.png', 'neko-yotei.png'] + [f'neko-{k}.png' for k in TH]
HIST = sorted(L.get('history', []), key=lambda h: str(h.get('date', '')), reverse=True)   # 2019年からの動き(年表)。新しい順
HIST_MIN = int(os.environ.get('NEWS_HIST_MIN', 3))   # 年表は、そのテーマに3件以上そろってから表に出す(スカスカの年表を出さない)
errors = []


def d_(s): return datetime.date.fromisoformat(s)
def jp(s, year=False, wd=True):
    d = d_(s)
    return (f'{d.year}年' if year else '') + f'{d.month}月{d.day}日' + (f'({WD[d.weekday()]})' if wd else '')
def md(s): d = d_(s); return f'{d.month}/{d.day}'
def e(s): return _h.escape(str(s), quote=False)
def isdate(s):
    try: d_(s); return True
    except Exception: return False


# ───────── 切り抜き帳の書き方を確かめる ─────────
def texts(it):
    return [it.get('title', ''), it.get('short', ''), it.get('lead', ''), it.get('cat', '')] + list(it.get('what', [])) + list(it.get('osaka', [])) \
        + [a + b for a, b in it.get('facts', [])] + [p for _, p in it.get('ukezara', [])]


def validate():
    ids = [x.get('id') for x in L['items']]
    if len(ids) != len(set(ids)): errors.append('id が重なっています')
    for k in IMG:
        if not os.path.exists(os.path.join(ROOT, 'news', 'img', k)): errors.append(f'猫の絵がありません: news/img/{k}')
    for it in L['items']:
        w = it.get('id', '?')
        for k in ('id', 'issue', 'released', 'posted', 'theme', 'title', 'short', 'lead', 'facts', 'what', 'osaka', 'cat', 'sources', 'ukezara', 'words'):
            if not it.get(k): errors.append(f'{w}: 「{k}」がありません')
        if errors and errors[-1].startswith(w): continue
        for k in ('issue', 'released', 'posted'):
            if not isdate(it[k]): errors.append(f'{w}: {k} の日付の形がちがいます(例 2026-11-16)')
        if isdate(it['issue']) and isdate(it['released']) and it['released'] > it['issue']: errors.append(f'{w}: 発表日(released)が号の日付(issue)より後です')
        if it['theme'] not in TH: errors.append(f'{w}: テーマ「{it["theme"]}」は themes にありません')
        if len(it['title']) > 70: errors.append(f'{w}: 見出し(title)は70字まで。いま{len(it["title"])}字')
        if len(it['short']) > 45: errors.append(f'{w}: 短い見出し(short)は45字まで。いま{len(it["short"])}字')
        if not (2 <= len(it['facts']) <= 5) or any(len(f) != 2 for f in it['facts']): errors.append(f'{w}: facts は [ラベル, 中身] を2〜5個')
        if not (1 <= len(it['osaka']) <= 3): errors.append(f'{w}: osaka(大阪で部屋を借りる人には)は1〜3段落')
        if not (2 <= len(it['words']) <= 5): errors.append(f'{w}: words は2〜5個')
        for s in it['sources']:
            if not all(s.get(k) for k in ('org', 'doc', 'date', 'url', 'kind')): errors.append(f'{w}: sources に org/doc/date/url/kind がそろっていません')
            elif not s['url'].startswith('https://') or s['kind'] not in KINDS or not isdate(s['date']): errors.append(f'{w}: sources の url(https)・kind({"/".join(KINDS)})・date を確かめてください')
        if not (1 <= len(it['ukezara']) <= 3): errors.append(f'{w}: ukezara(つなぐ特集)は1〜3本')
        for slug, _ in it['ukezara']:
            if not os.path.exists(os.path.join(ROOT, 'articles', slug + '.html')): errors.append(f'{w}: つなぐ特集 articles/{slug}.html がありません')
        for t in texts(it):
            for b in BANNED:
                if b in t: errors.append(f'{w}: 使わない言葉「{b}」が入っています')
            for tgt in re.findall(r'\[\[([^\]|]+)\|', t):
                if tgt.startswith('news:'):
                    if tgt[5:] not in ISSUES: errors.append(f'{w}: [[{tgt}|…]] の号がありません')
                elif not os.path.exists(os.path.join(ROOT, 'articles', tgt + '.html')): errors.append(f'{w}: [[{tgt}|…]] の記事がありません')
    for h in L.get('history', []):
        w = '年表 ' + str(h.get('date'))
        if h.get('theme') not in TH: errors.append(f'{w}: テーマ「{h.get("theme")}」は themes にありません')
        if not re.fullmatch(r'\d{4}(-\d{2}){0,2}', str(h.get('date', ''))): errors.append(f'{w}: date は 2019 / 2019-03 / 2019-03-05 のどれかの形')
        if not h.get('text'): errors.append(f'{w}: text がありません')
        if not isdate(str(h.get('added', ''))): errors.append(f'{w}: added(年表に足した日)が要ります')
        ss = h.get('sources') or []
        if not ss or any(not (s.get('org') and s.get('doc') and str(s.get('url', '')).startswith('https://')) for s in ss): errors.append(f'{w}: sources(org・doc・url)が要ります')
        for b in BANNED:
            if b in str(h.get('text', '')): errors.append(f'{w}: 使わない言葉「{b}」が入っています')
    for c in L.get('charts', []):
        w = 'グラフ ' + str(c.get('title'))
        if not c.get('themes') or any(t not in TH for t in c.get('themes', [])): errors.append(f'{w}: themes(どのテーマのページに出すか)を確かめてください')
        if not c.get('title') or not c.get('note'): errors.append(f'{w}: title と note が要ります')
        rs = c.get('rows') or []
        if len(rs) < 2 or any(len(r) < 2 or not isinstance(r[1], (int, float)) for r in rs): errors.append(f'{w}: rows は [ラベル, 数字] を2つ以上')
        for n in ('kw', 'vw'):
            if c.get(n) and not re.fullmatch(r'\d+(\.\d+)?em', str(c[n])): errors.append(f'{w}: {n}(欄の幅)は 5.4em のような形')
        ss = c.get('sources') or []
        if not ss or any(not (x.get('org') and x.get('doc') and str(x.get('url', '')).startswith('https://')) for x in ss): errors.append(f'{w}: sources(org・doc・url)が要ります')
        for b in BANNED:
            if b in str(c.get('title', '')) + str(c.get('note', '')): errors.append(f'{w}: 使わない言葉「{b}」が入っています')
    for u in L.get('upcoming', []):
        if u.get('date') and not isdate(u['date']): errors.append(f'upcoming: 日付の形がちがいます {u}')
        if not u.get('date') and not u.get('when'): errors.append(f'upcoming: date か when のどちらかが要ります {u}')


validate()
if errors:
    print('× 切り抜き帳に直すところがあります:'); [print('  -', x) for x in errors]; sys.exit(1)
if CHECK_ONLY:
    print('○ 切り抜き帳はOK:', len(ISSUES), '号 /', len(ITEMS), '件'); sys.exit(0)


# ───────── 部品 ─────────
def mk(s):
    """切り抜き帳の本文 → HTML(**太字** と [[リンク]] だけ)"""
    s = e(s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    def lk(m):
        tgt, lab = m.group(1), m.group(2)
        if tgt.startswith('news:'): return f'<a href="{tgt[5:]}.html">{lab}</a>'
        return f'<a href="../articles/{tgt}.html">{lab}</a>'
    return re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', lk, s)
def plain(s): return re.sub(r'\[\[[^\]|]+\|([^\]]+)\]\]', r'\1', s.replace('**', ''))
def cut(s, n):
    """文の切れ目(。)で、n字に近いところまで"""
    out = ''
    for part in re.findall(r'[^。]*。', s):
        if out and len(out) + len(part) > n: break
        out += part
    return out or s[:n]


_art = {}
def art(slug):
    """特集記事の番号と題(公開中の articles/ から読む)"""
    if slug not in _art:
        h = rd(os.path.join(ROOT, 'articles', slug + '.html'))
        no = re.search(r'<span class="cat">(?:レポート )?(No\.\d+)', h)
        t = re.search(r'<title>(.*?)</title>', h, re.S).group(1).split('|')[0].strip()
        _art[slug] = (no.group(1) if no else '特集', t)
    return _art[slug]


def page(title, desc, url, ld, body, script=''):
    h = SHELL
    for k, v in (('{{TITLE}}', title), ('{{DESC}}', desc), ('{{OGDESC}}', desc[:118]), ('{{URL}}', url), ('{{LD}}', ld), ('{{BODY}}', body), ('{{SCRIPT}}', script)):
        h = h.replace(k, v)
    return h


def catnote(img, say):
    return f'<div class="cat-note">\n      <img src="img/{img}" alt="" width="54" height="54" loading="lazy">\n      <p class="say">{say}</p>\n    </div>'
def lst(rows): return '<ul class="st-list">\n' + '\n'.join(f'      <li><b>{e(a)}</b><span class="m">{e(b)}</span></li>' for a, b in rows) + '\n    </ul>'
def cta_line(t, s, btn):
    return ('<div class="cta-band">\n      <p class="t">' + t + '</p>\n      <p class="s">' + s + '</p>\n      <div class="btns"><a class="btn btn-line" href="' + LINE_URL + '">' + btn + '</a></div>\n    </div>')
CTA_HEYA = cta_line('💬 いまの相場で住める部屋、LINEで3件送ります', '「通勤先・家賃の上限・こだわり1つ(駅・築年・設備など)」を送ってもらえれば、SUUMOの最新相場(' + SUUMO_DATE + '更新)の中から、ますだが3件選んでお返事します。内見はオンラインでも(無料・しつこい営業なし)。', 'LINEで3件もらう')
CTA_NEAGE = cta_line('💬 その値上げ、何パーセントで、相場と比べてどうか——無料で見ます', '「駅名・間取り・いまの家賃・値上げ後の家賃・更新日」をLINEで送ってもらえれば、SUUMOの最新相場(' + SUUMO_DATE + '更新)と比べて、値上げ後の家賃が相場の上か下かをお返事します。(無料・しつこい営業なし)', 'LINEで見てもらう')
AUTHOR = ('<div class="author">\n    <p class="who"><strong>住まらぼ 大阪福島店</strong>(運営: AS-PARTNERS株式会社)</p>\n    <p>宅地建物取引業免許:国土交通大臣(1)第10816号 所在地:〒553-0003 大阪府大阪市福島区福島5丁目3-7 エスティ西梅田ビル1F/TEL:06-4950-5432(担当ますだ直通 070-6450-0496)</p>\n  </div>')
NOTE = ('<p class="note">' + SERIES + 'について:役所や会社が発表した資料をもとに、住まらぼ 大阪福島店(宅建業者)が自分の言葉でまとめています。'
        '数字は発表資料のとおり、「当店の見方」と書いた部分は当店の意見です。大阪の相場の数字は、SUUMO沿線ページの1K/1DK(' + SUUMO_DATE + '更新)を当店が駅ごとに集計したもの(レポートNo.004)。'
        '内容に誤りを見つけたときは、訂正した日付を添えて直します。</p>')


def src_html(it):
    out = [f'<a href="{s["url"]}" target="_blank" rel="noopener">{e(s["org"])}「{e(s["doc"])}」</a>({jp(s["date"], year=True, wd=False)}・{s["kind"]})' for s in it['sources']]
    return '<p class="nw-src">出どころ: ' + ' / '.join(out) + '。数字は発表資料のとおりです。</p>'


def cards(it):
    cs = []
    for slug, p in it['ukezara']:
        no, t = art(slug)
        cs.append(f'      <a href="../articles/{slug}.html"><span class="nr-cat">{"レポート " + no if no.startswith("No.") else no}</span><b>{e(t)}</b><p>{e(p)}</p></a>')
    return ('<div class="next-read">\n      <div class="nr-title">🐾 くわしく読む(特集のレポート)</div>\n      <div class="nr-grid">\n' + '\n'.join(cs) + '\n      </div>\n    </div>')


def chart(c):
    """棒のグラフ。0の線を基準に、プラスは右、マイナスは左へ伸びる。数字は文字でも出す"""
    vals = [r[1] for r in c['rows']]
    lo, hi = min(0, min(vals)), max(0, max(vals)); span = (hi - lo) or 1
    zero = (0 - lo) / span * 100
    lis = []
    for r in c['rows']:
        label, v = r[0], r[1]
        txt = r[2] if len(r) > 2 and r[2] else (('+' if v > 0 else ('−' if v < 0 else '±')) + f'{abs(v):g}' + c.get('unit', '%'))
        w = abs(v) / span * 100
        left = zero if v >= 0 else zero - w
        lis.append(f'        <li><span class="k">{e(label)}</span><span class="t" aria-hidden="true"><i class="z" style="left:{zero:.1f}%"></i>'
                   f'<i class="b {"pos" if v >= 0 else "neg"}" style="left:{left:.1f}%;width:{max(w, 0.8):.1f}%"></i></span><span class="v">{e(txt)}</span></li>')
    src = ' / '.join(f'<a href="{x["url"]}" target="_blank" rel="noopener">{e(x["org"])}「{e(x["doc"])}」</a>' for x in c['sources'])
    # 文字の欄の幅(kw=左のラベル、vw=右の数字)。「84,672件」のように長い数字のときだけ広げる
    wd = ';'.join(f'--{n}:{c[n]}' for n in ('kw', 'vw') if c.get(n))
    return (f'    <div class="nw-chart">\n      <p class="ttl">{e(c["title"])}</p>\n      <ul' + (f' style="{wd}"' if wd else '') + '>\n' + '\n'.join(lis)
            + f'\n      </ul>\n      <p class="cap">{mk(c["note"])}<span class="s">出どころ: {src}</span></p>\n    </div>')


def hdate(s):
    """年表の日付の見せ方: 2019 → 2019年 / 2019-03 → 2019年3月 / 2019-03-05 → 2019年3月5日"""
    p = s.split('-')
    return f'{int(p[0])}年' + (f'{int(p[1])}月' if len(p) > 1 else '') + (f'{int(p[2])}日' if len(p) > 2 else '')


def row(x):
    """一覧やテーマのページに並べる、短信1本ぶんのカード"""
    return f'''      <li data-t="{x['theme']}"><a href="{x['issue']}.html">
        <img class="face" src="img/neko-{x['theme']}.png" alt="" width="52" height="52" loading="lazy">
        <span class="tx"><span class="d">{jp(x['issue'], year=True)}<span class="th">{TH[x['theme']]['label']}</span></span>
        <b>{e(x['title'])}</b>
        <span class="p">{e(cut(plain(x['lead']), 120))}</span></span>
      </a></li>'''


def item_block(it, multi):
    hx = 'h3' if multi else 'h2'
    h = []
    if multi: h.append(f'    <h2>{e(it["title"])}</h2>')
    h.append(f'    <p>{mk(it["lead"])}</p>')
    h.append(f'    <{hx}>何があった?</{hx}>')
    h.append('    ' + lst(it['facts']))
    h += [f'    <p>{mk(p)}</p>' for p in it['what']]
    h.append('    ' + src_html(it))
    h.append(f'    <{hx}>大阪で部屋を借りる人には</{hx}>')
    h.append('    <div class="nw-osaka">\n      <p class="who"><img src="img/shocho-point.png" alt="" width="60" height="60" loading="lazy"><b>所長の解説</b></p>\n'
             + '\n'.join(f'      <p>{mk(p)}</p>' for p in it['osaka']) + '\n    </div>')
    h.append('    ' + catnote(f'neko-{it["theme"]}.png', e(it['cat'])))
    h.append('    ' + cards(it))
    return '\n\n'.join(h)


def checked(name, html):
    """できたページの最後の確かめ(使わない言葉・タグの閉じ忘れ・絵)"""
    for w in BANNED:
        if w in html: errors.append(f'news/{name}: 使わない言葉「{w}」')
    b = html[html.find('<div class="wrap">'):html.find('<footer')]
    for t in ('div', 'ul', 'li', 'h1', 'h2', 'h3', 'p', 'a', 'span', 'b'):
        o, c = len(re.findall(r'<%s[\s>]' % t, b)), len(re.findall(r'</%s>' % t, b))
        if o != c: errors.append(f'news/{name}: <{t}> が {o} 個、</{t}> が {c} 個')
    for m in re.findall(r'src="img/([^"]+)"', b):
        if m not in IMG: errors.append(f'news/{name}: 絵 {m} がありません')
    return html


# ───────── 号ごとのページ ─────────
out = {}
for k, iss in enumerate(ISSUES):
    its = [x for x in ITEMS if x['issue'] == iss]
    first = its[0]; multi = len(its) > 1
    posted = max(x['posted'] for x in its)
    URL = f'{SITE}/news/{iss}.html'
    H1 = first['title'] if not multi else f'{SERIES} {jp(iss)}:' + '/'.join(x['short'] for x in its)
    TITLE = (first['short'] if not multi else '・'.join(x['short'] for x in its)) + f'|{SERIES} {md(iss)}'
    DESC = cut(plain(first['lead']), 125) + '大阪で部屋を借りる人にどう関係するかを、大阪の賃貸店がひとことで。'
    ld = json.dumps({"@context": "https://schema.org", "@type": "NewsArticle", "headline": H1[:108], "datePublished": posted,
                     "dateModified": max([posted] + [x['modified'] for x in its if x.get('modified')]),
                     "author": {"@type": "Organization", "name": "住まらぼ 大阪福島店"}, "publisher": {"@type": "Organization", "name": "AS-PARTNERS株式会社"},
                     "mainEntityOfPage": URL}, ensure_ascii=False)
    themes = '・'.join(dict.fromkeys(TH[x['theme']]['label'] for x in its))
    newer = ISSUES[k - 1] if k > 0 else None; older = ISSUES[k + 1] if k + 1 < len(ISSUES) else None
    nav = ('<p class="nw-nav">' + (f'<a href="{older}.html">← 前の号({md(older)})</a>' if older else '<span></span>')
           + f'<a href="theme-{first["theme"]}.html">「{TH[first["theme"]]["label"]}」をまとめて読む</a>'
           + '<a href="index.html">一覧へ</a>' + (f'<a href="{newer}.html">次の号({md(newer)}) →</a>' if newer else '<span></span>') + '</p>')
    late = '' if posted == iss else f'\n    <p class="note">この号は、創刊の前に出た発表を、{d_(posted).year}年{d_(posted).month}月の創刊のときにまとめて載せたものです。</p>\n'
    body = f'''<div class="wrap">
  <p class="crumb"><a href="../index.html">トップ</a> › <a href="index.html">{SERIES}</a> › {jp(iss)}</p>

  <div class="article-head">
    <a class="nw-plate" href="index.html"><img src="img/shocho-shiraberu.png" alt="" width="46" height="46"><span><b>{SERIES}</b><span class="m">{jp(iss, year=True)}・{themes}</span></span></a>
    <h1>{e(H1)}</h1>
  </div>

  <div class="article-body">
{chr(10).join(item_block(x, multi) for x in its)}

    {CTA_NEAGE if first['theme'] == 'neage' else CTA_HEYA}

    {NOTE}
{late}
    {nav}
  </div>

  {AUTHOR}
</div>
'''
    out[f'{iss}.html'] = checked(f'{iss}.html', page(TITLE, DESC, URL, ld, body))

# ───────── テーマごとのページ(上に最新の短信、下に2019年からの動き) ─────────
MADE = ST.get('history_made', '')          # 年表をまとめた時期(例: 2026年11月)
THEME_PAGES = [k for k in TH if any(x['theme'] == k for x in ITEMS) or sum(1 for h in HIST if h['theme'] == k) >= HIST_MIN]
theme_mod = {}
for k in THEME_PAGES:
    v = TH[k]; its = [x for x in ITEMS if x['theme'] == k]; hs = [h for h in HIST if h['theme'] == k]
    show_hist = len(hs) >= HIST_MIN
    theme_mod[k] = max([x['posted'] for x in its] + ([h['added'] for h in hs] if show_hist else []))
    URL = f'{SITE}/news/theme-{k}.html'
    TITLE = f'{v["label"]}のニュース' + ('と、2019年からの動き' if show_hist else '') + f'|{SERIES}'
    DESC = (f'{v["label"]}({v["desc"]})について、新しい発表の短信' + ('と、2019年からの動きの年表' if show_hist else '')
            + 'をまとめています。大阪で部屋を借りる人の目線で、大阪の賃貸店(宅建業者)が更新。')
    ld = json.dumps({"@context": "https://schema.org", "@type": "CollectionPage", "name": TITLE, "url": URL,
                     "publisher": {"@type": "Organization", "name": "AS-PARTNERS株式会社"}}, ensure_ascii=False)
    newest = ('<ul class="nw-list">\n' + '\n'.join(row(x) for x in its) + '\n    </ul>') if its else '<p>このテーマの短信は、発表があり次第ここに並びます。</p>'
    hist = ''
    if show_hist:
        blocks = []
        for y in sorted({h['date'][:4] for h in hs}, reverse=True):
            lis = '\n'.join(f'        <li><span class="d">{hdate(h["date"])}</span>{mk(h["text"])}<span class="s">出どころ: '
                            + ' / '.join(f'<a href="{s["url"]}" target="_blank" rel="noopener">{e(s["org"])}「{e(s["doc"])}」</a>' for s in h['sources'])
                            + '</span></li>' for h in hs if h['date'][:4] == y)
            blocks.append(f'      <h3>{y}年</h3>\n      <ul>\n{lis}\n      </ul>')
        charts = '\n'.join(chart(c) for c in L.get('charts', []) if k in c['themes'])
        hist = (f'\n    <h2>2019年からの動き</h2>\n    <p class="pt">当時の発表資料をさかのぼって調べ、{MADE}にまとめた記録です。年表は新しい年が上です。</p>\n'
                + (charts + '\n' if charts else '') + '    <div class="nw-hist">\n' + '\n'.join(blocks) + '\n    </div>\n')
    tcards = ''
    if v.get('ukezara'):
        cs = []
        for slug in v['ukezara']:
            no, t = art(slug)
            cs.append(f'      <a href="../articles/{slug}.html"><span class="nr-cat">{"レポート " + no if no.startswith("No.") else no}</span><b>{e(t)}</b><p>特集のレポート</p></a>')
        tcards = ('\n    <div class="next-read">\n      <div class="nr-title">🐾 くわしく読む(特集のレポート)</div>\n      <div class="nr-grid">\n' + '\n'.join(cs) + '\n      </div>\n    </div>\n')
    body = f'''<div class="wrap">
  <p class="crumb"><a href="../index.html">トップ</a> › <a href="index.html">{SERIES}</a> › {e(v["label"])}</p>

  <div class="article-head">
    <a class="nw-plate" href="index.html"><img src="img/neko-{k}.png" alt="" width="46" height="46"><span><b>{SERIES}</b><span class="m">テーマ別・新しい順</span></span></a>
    <h1>{e(v["label"])}のニュース</h1>
  </div>

  <div class="article-body">
    <p>入る話題は、{e(v["desc"])}。新しい短信が上に並びます。</p>

    <h2>最新の短信</h2>
    {newest}
{hist}{tcards}
    {CTA_NEAGE if k == 'neage' else CTA_HEYA}

    {NOTE}

    <p class="nw-nav"><a href="index.html">← 一覧へ</a><span></span></p>
  </div>

  {AUTHOR}
</div>
'''
    out[f'theme-{k}.html'] = checked(f'theme-{k}.html', page(TITLE, DESC, URL, ld, body))

# ───────── 一覧ページ ─────────
used = [t for t in TH if any(x['theme'] == t for x in ITEMS)]
chips = '<button type="button" class="chip on" data-t="all" id="nw-chip-all">すべて</button>' + ''.join(
    f'<button type="button" class="chip" data-t="{t}" id="nw-chip-{t}">{TH[t]["label"]}</button>' for t in used)
rows = '\n'.join(row(x) for x in ITEMS)


def tile(k):
    """テーマのタイル。いちばん新しい短信の見出しを添える"""
    v = TH[k]; its = [x for x in ITEMS if x['theme'] == k]
    inner = f'<img src="img/neko-{k}.png" alt="" width="44" height="44" loading="lazy"><span><b>{e(v["label"])}</b><span class="m">{e(v["desc"])}</span>'
    if its: inner += f'<span class="new"><i>{md(its[0]["issue"])}</i>{e(its[0]["short"])}</span>'
    elif k in THEME_PAGES: inner += '<span class="new">2019年からの動き(年表)</span>'
    inner += '</span>'
    return f'      <li><a href="theme-{k}.html">{inner}</a></li>' if k in THEME_PAGES else f'      <li><span class="off">{inner}</span></li>'
# 新しい短信があるテーマが上。同じなら themes の順のまま
order = sorted(TH, key=lambda k: (max([x['issue'] for x in ITEMS if x['theme'] == k], default=''), k in THEME_PAGES), reverse=True)
tiles = '\n'.join(tile(k) for k in order)
latest = max(ISSUES)
ups = '\n'.join(f'      <li><span class="w">{jp(u["date"]) if u.get("date") else e(u["when"])}</span>{e(u["label"])}<span class="n">{e(u["note"])}</span></li>'
                for u in L['upcoming'] if not u.get('date') or u['date'] > latest)
URL = f'{SITE}/news/'
TITLE = f'{SERIES}|{TAGLINE}'
DESC = ('、'.join(v['label'] for v in TH.values()) + '。役所や不動産会社の発表から、大阪で部屋を借りる人に関係するものだけを拾い、'
        '「大阪ではどうなる?」をひとこと添えてまとめる短信です。大阪の賃貸店(宅建業者)が更新。')
ld = json.dumps({"@context": "https://schema.org", "@type": "CollectionPage", "name": TITLE, "url": URL,
                 "publisher": {"@type": "Organization", "name": "AS-PARTNERS株式会社"}}, ensure_ascii=False)
body = f'''<div class="wrap">
  <p class="crumb"><a href="../index.html">トップ</a> › {SERIES}</p>

  <div class="nw-mast">
    <h1>{SERIES}</h1>
    <p class="tag">{TAGLINE}</p>
    <div class="who">
      <img src="img/shocho-shiraberu.png" alt="虫めがねで資料を調べる、住まらぼの所長(ねこ)" width="92" height="92">
      <p class="say">役所や不動産会社の発表を、所長が毎朝読んでいます。大阪で部屋を借りる人に関係するものだけ、短くお届けしますよ!</p>
    </div>
    <p class="rule"><span>住まらぼ 大阪福島店 発行</span><span>平日の朝に更新</span></p>
  </div>

  <div class="article-body">
    <p>どの短信にも、<strong>「大阪ではどうなる?」</strong>を所長がひとこと添えています。発表があった日の翌朝に更新し、伝えることのない日はお休みします。</p>

    <h2>テーマごとの最新</h2>
    <p class="pt">新しい短信が出たテーマが上に来ます。押すと、そのテーマだけをまとめて読めます。</p>
    <ul class="nw-tiles">
{tiles}
    </ul>

    <h2>新しい順に読む</h2>
    <div class="nw-chips" id="nw-chips">{chips}</div>
    <ul class="nw-list" id="nw-list">
{rows}
    </ul>

    <h2>これから出る発表</h2>
    {catnote('neko-yotei.png', '日付が決まっている発表は、先に並べておきます。出た朝にお届けしますよ!')}
    <ul class="nw-up">
{ups}
    </ul>

    {CTA_HEYA}

    {NOTE}
  </div>

  {AUTHOR}
</div>
'''
script = '''<script>
(function(){var cs=document.querySelectorAll('#nw-chips .chip'),ls=document.querySelectorAll('#nw-list li');
cs.forEach(function(c){c.addEventListener('click',function(){var t=c.getAttribute('data-t');
cs.forEach(function(x){x.classList.toggle('on',x===c)});
ls.forEach(function(l){l.hidden=!(t==='all'||l.getAttribute('data-t')===t)});});});})();
</script>
'''
out['index.html'] = checked('index.html', page(TITLE, DESC, URL, ld, body, script))

if errors:
    print('× できたページに直すところがあります(何も書き込んでいません):'); [print('  -', x) for x in errors]; sys.exit(1)

# ───────── 書き込み ─────────
ND = os.path.join(ROOT, 'news')
os.makedirs(ND, exist_ok=True)
for f in os.listdir(ND):                                   # 切り抜き帳から消した号は、ページも消す
    if re.fullmatch(r'(\d{4}-\d{2}-\d{2}|theme-[a-z]+)\.html', f) and f not in out: os.remove(os.path.join(ND, f))
for name, html in out.items(): wr(os.path.join(ND, name), html)

# サイトマップ: ニュースの行をいったん外して、入れ直す
SM = os.path.join(ROOT, 'sitemap.xml'); sm = rd(SM)
sm = re.sub(r'  <url>\s*<loc>' + re.escape(SITE) + r'/news/[^<]*</loc>.*?</url>\n', '', sm, flags=re.S)
def url(loc, lastmod, freq, pri): return f'  <url>\n    <loc>{loc}</loc>\n    <lastmod>{lastmod}</lastmod>\n    <changefreq>{freq}</changefreq>\n    <priority>{pri}</priority>\n  </url>\n'
block = url(SITE + '/news/', max(x['posted'] for x in ITEMS), 'daily', '0.8')
for iss in sorted(ISSUES):
    its = [x for x in ITEMS if x['issue'] == iss]
    block += url(f'{SITE}/news/{iss}.html', max([x['posted'] for x in its] + [x['modified'] for x in its if x.get('modified')]), 'monthly', '0.6')
for k in THEME_PAGES: block += url(f'{SITE}/news/theme-{k}.html', theme_mod[k], 'weekly', '0.7')
assert sm.count('</urlset>') == 1
wr(SM, sm.replace('</urlset>', block + '</urlset>'))

print('○', SERIES, ':', len(ISSUES), '号 /', len(ITEMS), '件、テーマのページ', len(THEME_PAGES), '枚 を news/ に書き込みました。年表は',
      len(HIST), '件(表に出ているテーマ:', '・'.join(TH[k]['label'] for k in THEME_PAGES if sum(1 for h in HIST if h['theme'] == k) >= HIST_MIN) or 'まだなし', ')。')
