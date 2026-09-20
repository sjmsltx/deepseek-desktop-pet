# office_probe.ps1 — 在**独立进程**里探测本机可用的办公接口
#
# 为什么必须独立进程：COM 在 RPC 服务器异常时会抛 **Windows 致命异常**
# （0x8007006ba / 0x8007006be），Python 的 try/except **抓不住**，会直接把宿主进程打崩
# （2026-09-20 实测：office_doc 的 info 探测曾把整个 pytest 进程打崩）。
# 这里把探测隔离到子进程：崩也只崩探测进程，主进程只读结果。
#
# 输出：一行 JSON，如 {"sheet":{"prog_id":"KET.Application","version":"12.1.0.28022"}}
$ErrorActionPreference = 'SilentlyContinue'
$pairs = @(
  @('sheet',  'KET.Application'),
  @('sheet',  'Excel.Application'),
  @('doc',    'KWPS.Application'),
  @('doc',    'Word.Application'),
  @('slides', 'KWPP.Application'),
  @('slides', 'PowerPoint.Application')
)
$out = @{}
foreach ($p in $pairs) {
  $kind = $p[0]; $prog = $p[1]
  if ($out.ContainsKey($kind)) { continue }
  $app = $null
  try {
    $app = New-Object -ComObject $prog
    $ver = ''
    try { $ver = [string]$app.Version } catch { }
    $out[$kind] = @{ prog_id = $prog; version = $ver }
  } catch { }
  finally {
    if ($null -ne $app) {
      try { $app.Quit() } catch { }
      try { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) } catch { }
      $app = $null
      [GC]::Collect()
    }
  }
}
$out | ConvertTo-Json -Compress -Depth 4
