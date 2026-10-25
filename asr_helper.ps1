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
    [switch]$Check,
    [switch]$List
)

$ErrorActionPreference = 'Stop'

# ---------- 输出编码：必须固定 UTF-8 ----------
# 调用方（asr.py）用 CREATE_NO_WINDOW 启动本脚本 —— 没有控制台时，
# PowerShell 5.1 按系统 ANSI 代码页输出（本机 GBK），而 Python 侧按 UTF-8 解码
# ⇒ 中文全成乱码：错误提示读不出、识别成功的文本填进输入框也是乱码。
# 实测 2026-10-21 对照：有控制台时是 UTF-8，CREATE_NO_WINDOW 时变成 GBK。
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }
try { $OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }

# ---------- SAPI 备用路径（System.Speech，不依赖 OneCore 隐私策略）----------
function Invoke-SapiRecognize($Lang) {
    try { Add-Type -AssemblyName System.Speech -ErrorAction Stop } catch {
        Write-Output "ERR|System.Speech 不可用：$($_.Exception.Message)"
        exit 21
    }
    try {
        # 旧版这里创建了 $ci 却从未使用 —— 识别器其实一直是"默认那个"。
        # 现在按 $Lang 明确挑一个已装识别器；挑不到就用默认，保证不至于更差。
        $rec = $null
        foreach ($ri in [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers()) {
            if ($ri.Culture.Name -like "$Lang*") {
                $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine($ri)
                break
            }
        }
        if ($null -eq $rec) {
            $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
        }
        $rec.SetInputToDefaultAudioDevice()
        $rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
        # 与 WinRT 对齐：4 秒。两条路各 4 秒，总时长从约 13 秒降到约 8 秒
        # （实测一次点击太久，使用者会以为按钮坏了）
        $rec.InitialSilenceTimeout = [TimeSpan]::FromSeconds(4)
        $rec.BabbleTimeout = [TimeSpan]::FromSeconds(4)
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

# ---------- 只列举识别器（给 asr.py 判断"还能不能用"用）----------
if ($List) {
    try { Add-Type -AssemblyName System.Speech -ErrorAction Stop } catch {
        Write-Output "ERR|System.Speech 不可用：$($_.Exception.Message)"
        exit 21
    }
    try {
        $names = @([System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() |
                   ForEach-Object { $_.Culture.Name })
    } catch {
        Write-Output "ERR|枚举识别器失败：$($_.Exception.Message)"
        exit 24
    }
    Write-Output ("LIST|" + ($names -join ','))
    exit 0
}

if ($Engine -eq 'sapi') {
    Invoke-SapiRecognize $Lang
}

# ---------- 编译识别约束（少了这一步 RecognizeAsync 必抛 0x80131509）----------
# 实测 2026-10-25 三组对照：
#   直接 RecognizeAsync          → InvalidOperationException 0x80131509
#   先 CompileConstraintsAsync   → CompilationResult.Status = Success，识别正常返回
#   ⇒ 过去每一次都死在这一步，于是全部降级到 SAPI（中文 5 句只对 2 句、慢 5~7 秒），
#     使用者体感就是「时灵时不灵」。
# 把异常压成一行，并**带上 HRESULT** —— 中文系统上 .NET 常只给本地化文案
# （「无法找到与此错误代码关联的文本」），不带错误码就只能靠文案猜类型。
# 我 2026-10-21 就是这么猜错的：把 0x80131509 猜成隐私策略，白折腾四天。
function Describe-Exception($ErrorRecord) {
    $e = $ErrorRecord.Exception
    while ($e.InnerException) { $e = $e.InnerException }
    $msg = ($e.Message -replace "`r?`n", ' ').Trim()
    $hr = '0x' + ('{0:X8}' -f $e.HResult)
    return "$msg [$hr]"
}

function Initialize-WinRtRecognizer($Recognizer) {
    $op = $Recognizer.CompileConstraintsAsync()
    $res = Await-WinRt $op ([Windows.Media.SpeechRecognition.SpeechRecognitionCompilationResult])
    if ($null -eq $res) { return 'null' }
    return [string]$res.Status
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
        # 2026-10-25：旧版只读 CurrentLanguage 就报 OK —— 那只证明「能创建对象」，
        # 证明不了「能识别」。实测旧 -Check 返回 OK 的同时，识别每次都抛 0x80131509。
        # 现在把约束编译状态一并报出，能力检测才反映真实可用性。
        $st = Initialize-WinRtRecognizer $rec
        Write-Output "OK|$cur|$cur|compile=$st"
        exit 0
    } catch {
        Write-Output ("ERR|" + (Describe-Exception $_))
        exit 5
    }
}

try {
    # 关掉系统自带的那套 UI 提示（我们只要文本，不要它的确认框）
    try {
        $rec.UIOptions.AudiblePrompt = ''
        $rec.UIOptions.DisplayText = ''
        $rec.UIOptions.IsReadBackEnabled = $false
        $rec.UIOptions.ShowConfirmation = $false
    } catch { }

    # 放宽三个超时（默认很紧，人还没开口就结束了 —— 这是"点了没反应"的一半原因）
    #   InitialSilenceTimeout：开始等多久。3 秒太短，改成 6 秒，给"按下后想一下再说"留余量
    #   BabbleTimeout：听到噪音时最多再等多久
    #   EndSilenceTimeout：句尾静音判定。0.15 秒会把句子中间的停顿当成说完
    try {
        $rec.Timeouts.InitialSilenceTimeout = [TimeSpan]::FromSeconds(4)
        $rec.Timeouts.BabbleTimeout = [TimeSpan]::FromSeconds(8)
        $rec.Timeouts.EndSilenceTimeout = [TimeSpan]::FromSeconds(0.9)
    } catch { }

    $compileStatus = Initialize-WinRtRecognizer $rec
    if ($compileStatus -ne 'Success') {
        Write-Output "ERR|识别约束编译未成功（$compileStatus），这条识别路径用不了"
        exit 7
    }

    # 单句识别：说完停顿即结束
    $op = $rec.RecognizeAsync()
    $result = Await-WinRt $op ([Windows.Media.SpeechRecognition.SpeechRecognitionResult])
    $txt = ''
    if ($result) { $txt = [string]$result.Text }
    $conf = ''
    if ($result) { $conf = [string]$result.Confidence }
    if ([string]::IsNullOrWhiteSpace($txt) -and $conf -eq 'Rejected') {
        # Rejected = 听到了声音但不敢认（噪音 / 太轻 / 口音）。这与「压根没听到」是两回事，
        # 分开报，Python 侧才能给出不同提示。
        Write-Output 'REJECTED|听到了声音但没听准'
        exit 8
    }
    Write-Output "OK|$conf|$txt"
    exit 0
} catch {
    Write-Output ("ERR|识别失败：" + (Describe-Exception $_))
    exit 6
}
