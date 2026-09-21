# asr_helper.ps1 —— 离线语音识别（v6.66，语音输入；v6.77 加 SAPI 备用路径）
# 用法：powershell -File asr_helper.ps1 -Check                       # 只检查本机能否识别
#       powershell -File asr_helper.ps1 -Lang zh-CN              # 单句识别（WinRT）
#       powershell -File asr_helper.ps1 -Lang zh-CN -Engine sapi # 单句识别（SAPI 备用路径）
#
# 说明：
# - 默认走 WinRT SpeechRecognizer（Windows 自带，中文语言包已装时离线可用，不联网、零依赖）
# - **v6.77 新增 SAPI 备用路径**：WinRT 常被 OneCore 语音隐私策略拦住（实测本机就是），
#   System.Speech 走的是另一套识别栈，**不依赖那个策略**；两条都试过了就如实报错。
# - 输出契约：成功 → "OK|<置信度>|<文本>"；失败 → "ERR|<原因>"
# - 调用方（Python）用 CREATE_NO_WINDOW 启动，不会闪控制台；超时由 Python 侧 kill
param(
    [string]$Lang = 'zh-CN',
    [string]$Engine = 'winrt',
    [switch]$Check
)

$ErrorActionPreference = 'Stop'

# ---------- SAPI 备用路径（System.Speech，不依赖 OneCore 隐私策略）----------
function Invoke-SapiRecognize($Lang) {
    try { Add-Type -AssemblyName System.Speech -ErrorAction Stop } catch {
        Write-Output "ERR|System.Speech 不可用：$($_.Exception.Message)"
        exit 21
    }
    try {
        $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
        $rec.SetInputToDefaultAudioDevice()
        try {
            $ci = [System.Globalization.CultureInfo]::GetCultureInfo($Lang)
            $rec.RecognizerInfo.Culture.Name | Out-Null
            $rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
        } catch {
            $rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
        }
        $rec.InitialSilenceTimeout = [TimeSpan]::FromSeconds(6)
        $rec.BabbleTimeout = [TimeSpan]::FromSeconds(6)
        # 注意：桌面 SAPI（System.Speech）的同步方法就叫 Recognize()
        # （没有 RecognizeOnce / RecognizeOnceAsync 这两个名字 —— 实测列方法确认）
        $res = $rec.Recognize()
        if ($res -eq $null) {
            Write-Output 'ERR|没听清（SAPI 超时）'
            exit 22
        }
        Write-Output ("OK|{0}|{1}" -f $res.Confidence, $res.Text)
        exit 0
    } catch {
        Write-Output ("ERR|SAPI 识别失败：" + ($_.Exception.Message -replace "`r?`n", ' '))
        exit 23
    }
}

if ($Engine -eq 'sapi') {
    Invoke-SapiRecognize $Lang
}

function Await-WinRt($WinRtTask, $ResultType) {
    try { Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop } catch { }
    $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]
    $netTask = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

try {
    [void][Windows.Media.SpeechRecognition.SpeechRecognizer, Windows.Media.SpeechRecognition, ContentType = WindowsRuntime]
    [void][Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
} catch {
    Write-Output "ERR|WinRT 语音组件不可用：$($_.Exception.Message)"
    exit 3
}

try {
    $language = New-Object Windows.Globalization.Language($Lang)
    $rec = New-Object Windows.Media.SpeechRecognition.SpeechRecognizer($language)
} catch {
    try {
        $rec = New-Object Windows.Media.SpeechRecognition.SpeechRecognizer
    } catch {
        Write-Output "ERR|无法创建识别器（可能缺语音语言包）：$($_.Exception.Message)"
        exit 4
    }
}

if ($Check) {
    try {
        $cur = $rec.CurrentLanguage.LanguageTag
        $topic = ([Windows.Media.SpeechRecognition.SpeechRecognizer]::SupportedTopicLanguages |
                  ForEach-Object { $_.LanguageTag }) -join ','
        Write-Output "OK|$cur|$topic"
        exit 0
    } catch {
        Write-Output "ERR|$($_.Exception.Message)"
        exit 5
    }
}

try {
    # 单句识别：说完停顿即结束
    $op = $rec.RecognizeAsync()
    $result = Await-WinRt $op ([Windows.Media.SpeechRecognition.SpeechRecognitionResult])
    $txt = ''
    if ($result) { $txt = [string]$result.Text }
    $conf = ''
    if ($result) { $conf = [string]$result.Confidence }
    Write-Output "OK|$conf|$txt"
    exit 0
} catch {
    Write-Output ("ERR|识别失败：" + ($_.Exception.Message -replace "`r?`n", ' '))
    exit 6
}
