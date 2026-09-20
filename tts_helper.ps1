# tts_helper.ps1 —— 离线语音合成（v6.63，语音 P0）
# 用法：powershell -File tts_helper.ps1 -Text "你好" -Out C:\path\out.wav [-Engine winrt|sapi] [-Voice 名字] [-Rate 0]
#
# 说明：
# - 默认走 WinRT（Windows.Media.SpeechSynthesis）—— 音质比 SAPI 自然，系统自带、离线、零依赖
# - WinRT 失败时自动回退 SAPI（System.Speech），保证「至少能出声」
# - 只输出 wav 文件，播放交给调用方（Python 侧用 winsound 异步播放，便于打断）
param(
    [string]$Text = '',
    [string]$Out = '',
    [string]$Engine = 'winrt',
    [string]$Voice = '',
    [int]$Rate = 0,
    [switch]$ListVoices
)

$ErrorActionPreference = 'Stop'

if ($ListVoices) {
    # 供设置页“列出声线”用：每行 winrt:<名>|<语言>|<性别> 或 sapi:<名>|<区域>|<性别>
    try {
        [void][Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
        foreach ($v in [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices) {
            "winrt:$($v.DisplayName)|$($v.Language)|$($v.Gender)"
        }
    } catch { }
    try {
        Add-Type -AssemblyName System.Speech
        $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
        foreach ($v in $s.GetInstalledVoices()) {
            "sapi:$($v.VoiceInfo.Name)|$($v.VoiceInfo.Culture)|$($v.VoiceInfo.Gender)"
        }
        $s.Dispose()
    } catch { }
    exit 0
}

if (-not $Text -or -not $Out) { Write-Error '需要 -Text 与 -Out'; exit 2 }

function Await-WinRt($WinRtTask, $ResultType) {
    # PowerShell 5.1 没有原生 await，用反射把 WinRT 异步转成 .NET Task
    # （必须先加载 System.Runtime.WindowsRuntime，否则找不到 WindowsRuntimeSystemExtensions 类型）
    try { Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop } catch { }
    $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]
    $netTask = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

function Save-StreamToFile($stream, $path) {
    [void][Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]
    $size = [uint32]$stream.Size
    $reader = [Windows.Storage.Streams.DataReader]::new($stream.GetInputStreamAt(0))
    Await-WinRt ($reader.LoadAsync($size)) ([uint32]) | Out-Null
    $bytes = New-Object byte[] $size
    $reader.ReadBytes($bytes)
    [System.IO.File]::WriteAllBytes($path, $bytes)
}

function Invoke-Sapi {
    Add-Type -AssemblyName System.Speech
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    if ($Voice) {
        $v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Name -like "*$Voice*" } | Select-Object -First 1
        if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
    }
    # SAPI Rate: -10 ~ 10
    $s.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
    $s.SetOutputToWaveFile($Out)
    $s.Speak($Text)
    $s.Dispose()
}

function Invoke-WinRt {
    [void][Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
    $syn = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
    if ($Voice) {
        $v = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices |
             Where-Object { $_.DisplayName -like "*$Voice*" } | Select-Object -First 1
        if ($v) { $syn.Voice = $v }
    }
    $stream = Await-WinRt ($syn.SynthesizeTextToStreamAsync($Text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
    Save-StreamToFile $stream $Out
}

$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

$ok = $false
if ($Engine -eq 'winrt') {
    try {
        Invoke-WinRt
        if (Test-Path $Out) { $ok = $true }
    } catch {
        Write-Output "winrt 失败，回退 SAPI：$($_.Exception.Message)"
    }
}
if (-not $ok) {
    try {
        Invoke-Sapi
        if (Test-Path $Out) { $ok = $true; $Engine = 'sapi' }
    } catch {
        Write-Error "sapi 也失败：$($_.Exception.Message)"
        exit 2
    }
}

if ($ok) {
    $size = (Get-Item $Out).Length
    Write-Output "OK engine=$Engine bytes=$size out=$Out"
    exit 0
}
Write-Error '没有产出音频文件'
exit 3
