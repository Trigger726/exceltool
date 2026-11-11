r"""Exercise the real Windows WebView2 UI and bridge against disposable workbooks.

Run after building the frontend: .venv\Scripts\python.exe -X utf8 tools\app_probe.py
Pass --screenshots to refresh the four desktop screenshots in docs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from openpyxl import Workbook, load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))

from sheetkit.api import SheetKitApi
from sheetkit.shell import APP_TITLE, _register_drop_target, load_index


def workbook(path: Path, rows: list[list]) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = '台账'
    for row in rows:
        sheet.append(row)
    book.save(path)


def exercise(window, directory: Path, screenshots: bool, checks: dict) -> None:
    js = window.evaluate_js

    def wait(expr):
        started = time.monotonic()
        while time.monotonic() - started < 15:
            if js(f'Boolean({expr})'):
                return
            time.sleep(0.075)
        raise AssertionError(f'Timed out waiting for {expr}')

    def heading(title):
        wait(f'document.querySelector("main h1")?.textContent.trim() === {json.dumps(title)}')

    def click(label):
        selector = f'[...document.querySelectorAll("button")].find(b => b.textContent.trim() === {json.dumps(label)} && !b.disabled)'
        wait(selector)
        js(f'{selector}.click()')

    def input_value(selector, value):
        js(f"""(() => {{
            const input = document.querySelector({json.dumps(selector)});
            input.value = {json.dumps(value)};
            input.dispatchEvent(new Event('input', {{bubbles:true}}));
        }})()""")

    def capture(name):
        if not screenshots:
            return
        js("""document.querySelectorAll('[aria-label="关闭提示"]').forEach(button => button.click())""")
        wait("""!document.querySelector('[aria-label="关闭提示"]')""")
        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
        from System import Action
        from System.IO import MemoryStream

        native = window.native
        stream = MemoryStream()
        capture_tasks = []

        def start_capture():
            capture_tasks.append(native.webview.CoreWebView2.CapturePreviewAsync(
                CoreWebView2CapturePreviewImageFormat.Png, stream
            ))

        try:
            native.Invoke(Action(start_capture))
            capture_tasks[0].GetAwaiter().GetResult()
            target = ROOT / 'docs' / f'screenshot-{name}.png'
            target.write_bytes(bytes(stream.ToArray()))
            print(f'CAPTURED {target}', flush=True)
        finally:
            stream.Dispose()

    def route(path, title):
        js(f'location.hash = {json.dumps(path)}')
        heading(title)

    def drop(paths, selector=None):
        if selector:
            js(f'document.querySelector({json.dumps(selector)}).dispatchEvent(new MouseEvent("mouseenter"))')
        js(f'window.sheetkitDrop({json.dumps([str(path) for path in paths])})')

    def export(name):
        output = directory / f'{name}.xlsx'
        js(f"""
            window._realPicker = window._realPicker || window.pywebview.api.choose_files;
            window.pywebview.api.choose_files = (payload) => payload.kind === 'save'
              ? Promise.resolve({{ok:true, paths:[{json.dumps(str(output))}]}})
              : window._realPicker(payload);
        """)
        click('导出报告' if name == 'compare' else '导出文件')
        wait('document.querySelector("[data-export-feedback]")')
        assert output.is_file()
        return load_workbook(output)

    old = directory / '旧版.xlsx'
    new = directory / '新版.xlsx'
    extra = directory / '补充.xlsx'
    clean = directory / '清洗台账.xlsx'
    workbook(old, [['物料编码', '名称', '数量'], *[[f'{i:05}', ' 甲 ', i] for i in range(65)]])
    workbook(new, [['库存台账'], ['物料编码', '名称', '数量'],
                   *[[f'{i:05}', '甲', i + 1] for i in range(65)]])
    workbook(extra, [['物料编号', '数量'], ['1234567890123456789', 3]])
    workbook(clean, [['订单号', '名称', '日期', '数量'],
                     ['001', ' 甲 ', '日期错误', '未知'], ['001', '乙', '2026-01-01', 2]])

    wait('window.sheetkitDrop && window.pywebview?.api')
    heading('SheetKit 表格效率助手')
    assert js("location.protocol") == 'about:'
    assert js('document.querySelectorAll("main button").length') == 3
    assert js('!document.querySelector("vite-error-overlay")')
    checks['home_about_blank'] = True
    capture('home')

    js('document.querySelector("aside button").click()')
    wait('document.documentElement.classList.contains("dark")')
    js('document.querySelector("aside button").click()')
    wait('!document.documentElement.classList.contains("dark")')
    checks['theme'] = True

    route('#/compare', '表格对比')
    from System import Action

    window.resize(900, 600)
    window.native.Invoke(Action(lambda: setattr(window.native.webview, 'ZoomFactor', 1.25)))
    wait('innerWidth < 760 && devicePixelRatio >= 1.24')
    assert js('document.querySelector("main").scrollWidth === document.querySelector("main").clientWidth')
    checks['compact_layout'] = js('JSON.stringify({width:innerWidth,height:innerHeight,dpi:devicePixelRatio})')
    capture('compact')
    window.native.Invoke(Action(lambda: setattr(window.native.webview, 'ZoomFactor', 1.0)))
    window.resize(1100, 720)
    drop([old], '.file-picker:first-child')
    wait('document.body.innerText.includes("旧版.xlsx")')
    drop([new], '.file-picker:nth-child(2)')
    wait('document.body.innerText.includes("推荐第 2 行")')
    click('使用 物料编码')
    click('开始对比')
    wait('document.body.innerText.includes("3 · 对比结果")')
    wait('document.body.innerText.includes("共 65 行")')
    js('document.querySelector("[data-result] button[title=下一页]:not(:disabled)").click()')
    wait('[...document.querySelectorAll("[data-result] span")].some(s => s.textContent === "2 / 2")')
    input_value('input[type=search]', '00042')
    wait('document.body.innerText.includes("筛选后 1 / 65")')
    checks['compare_recommendation_paging_filter'] = True
    capture('compare')
    with_export = export('compare')
    try:
        assert with_export['修改明细'].auto_filter.ref == 'A1:G66'
        assert '细微差异' in with_export.sheetnames
    finally:
        with_export.close()
    checks['compare_export'] = True

    # A large input leaves enough time to exercise cancellation during reading.
    large = directory / '大表.xlsx'
    workbook(large, [['物料编码', '名称', '数量'],
                     *[[f'{i:05}', '甲', i] for i in range(15_000)]])
    drop([large], '.file-picker:first-child')
    wait('document.body.innerText.includes("大表.xlsx")')
    click('使用 物料编码')
    click('开始对比')
    wait('document.querySelector("[role=progressbar]")')
    click('取消')
    wait('document.body.innerText.includes("已取消本次对比")')
    checks['progress_and_cancel'] = True

    route('#/merge', '批量合并')
    drop([old, extra])
    click('确认使用推荐')
    wait('document.body.innerText.includes("已应用列名对应关系")')
    js('document.querySelector("details.advanced").open = true')
    input_value('input[placeholder="模板名称"]', '月度合并')
    click('保存模板')
    wait('document.body.innerText.includes("已保存模板")')
    click('补充.xlsx')
    click('恢复此文件原列名')
    wait('document.body.innerText.includes("确认使用推荐")')
    click('应用模板')
    wait('!document.body.innerText.includes("确认使用推荐")')
    click('开始合并')
    wait('document.body.innerText.includes("3 · 合并结果")')
    capture('merge')
    with_export = export('merge')
    try:
        rows = list(with_export['合并结果'].values)
        assert len(rows) == 67 and rows[-1][0] == '1234567890123456789'
    finally:
        with_export.close()
    checks['merge_alias_template_export'] = True

    route('#/clean', '数据清洗')
    drop([directory / 'invalid.xls'])
    wait('document.body.innerText.includes("invalid.xls")')
    drop([clean])
    click('应用推荐')
    click('开始清洗')
    wait('document.querySelector("tr.bg-danger-soft") && document.querySelector("tr.bg-warning-soft")')
    capture('clean')
    js('[...document.querySelectorAll("details")].find(d => d.innerText.includes("设置导出列")).open = true')
    js("""document.querySelector('[aria-label="上移 名称"]').click()""")
    input_value('input[placeholder="模板名称"]', '清洗输出')
    click('保存模板')
    wait('document.body.innerText.includes("已保存模板")')
    click('恢复所有列')
    click('应用模板')
    with_export = export('clean')
    try:
        assert with_export['清洗结果']['A1'].value == '名称'
        assert with_export['清洗结果']['B2'].value == '001'
        assert with_export['清洗结果']['A2'].fill.fgColor.rgb == 'FFFDECEC'
    finally:
        with_export.close()
    js('document.querySelector("details.advanced").open = true')
    js('document.querySelector("input[value=keep_first]").click()')
    wait('document.body.innerText.includes("删除重复数据的影响预览")')
    click('开始清洗')
    wait('document.querySelector("dialog[open]")')
    js('document.querySelector("dialog button.btn-default").click()')
    wait('!document.querySelector("dialog[open]")')
    click('开始清洗')
    click('确认删除')
    wait('document.body.innerText.includes("已按") && document.body.innerText.includes("删除 1 行重复数据")')
    checks['clean_recommendation_impact_confirmation_tint_template_export'] = True

    checks['javascript_errors'] = json.loads(js('JSON.stringify(window.__errors)'))
    assert not checks['javascript_errors']


def main() -> int:
    import webview
    from webview.dom import _dnd_state

    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshots', action='store_true')
    args = parser.parse_args()
    instrument = """<script>
      window.__errors = [];
      for (const type of ['error', 'unhandledrejection']) {
        window.addEventListener(type, e => window.__errors.push(String(e.message || e.reason)));
      }
      const logError = console.error;
      console.error = (...args) => { window.__errors.push(args.map(String).join(' ')); logError(...args); };
    </script>"""
    html = load_index().replace('<head>', '<head>' + instrument, 1)
    checks = {}
    with tempfile.TemporaryDirectory(prefix='sheetkit-e2e-') as work:
        os.environ['LOCALAPPDATA'] = work
        api = SheetKitApi()
        window = webview.create_window(APP_TITLE, html=html, js_api=api, width=1100,
                                       height=720, min_size=(700, 480), resizable=True)
        api._attach(window)

        def on_loaded():
            try:
                _register_drop_target(window)
                assert _dnd_state['num_listeners'] > 0
                checks['native_drop_listener'] = True
                exercise(window, Path(work), args.screenshots, checks)
            except Exception as exc:
                checks['failure'] = repr(exc)
                try:
                    checks['screen_text'] = window.evaluate_js('document.body.innerText.slice(-1200)')
                except Exception:
                    pass
            finally:
                api.shutdown()
                window.destroy()

        window.events.loaded += on_loaded
        webview.start(gui='edgechromium', http_server=False)

    print('PROBE_RESULTS ' + json.dumps(checks, ensure_ascii=False), flush=True)
    return 0 if 'javascript_errors' in checks and 'failure' not in checks else 1


if __name__ == '__main__':
    sys.exit(main())
