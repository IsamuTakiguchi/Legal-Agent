; Legal-Agent のインストーラ定義（NSIS 3）。tools/build_installer.sh からビルドする。
;
; 方針:
;   - 管理者権限も UAC も不要（RequestExecutionLevel user）。導入先は今までと同じ
;     %LOCALAPPDATA%\Legal-Agent なので、install.ps1 の relocate 判定が「同じ場所」と見なし、
;     コピーが二重にならない。
;   - 同梱するのは実行に必要なファイルだけ（tests/ docs/ tools/ .github/ は入れない）。
;   - .env / data / python / logs / .update.json は同梱しないので、再インストールでも
;     利用者の API キー・索引・履歴は上書きされない。
;   - Python 本体とライブラリの導入は今までどおり install.ps1 に任せる。
;
; 必須の -D 引数: VERSION（4 桁）, DISPLAY_VERSION, PAYLOAD（同梱するフォルダ）, OUTFILE

Unicode true
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define APP_NAME "Legal-Agent"
!define PUBLISHER "Legal-Agent"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

Name "${APP_NAME}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\${APP_NAME}"
RequestExecutionLevel user
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${VERSION}"
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "FileDescription" "Legal-Agent セットアップ"
VIAddVersionKey "FileVersion" "${DISPLAY_VERSION}"
VIAddVersionKey "ProductVersion" "${DISPLAY_VERSION}"
VIAddVersionKey "CompanyName" "${PUBLISHER}"
VIAddVersionKey "LegalCopyright" ""

!define MUI_ICON "${PAYLOAD}\legal_agent\static\legal-agent.ico"
!define MUI_UNICON "${PAYLOAD}\legal_agent\static\legal-agent.ico"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "Legal-Agent を導入します"
!define MUI_WELCOMEPAGE_TEXT "判例と手持ちの書籍 PDF を横断して調べる法務リサーチのアプリです。$\r$\n$\r$\n導入先: $LOCALAPPDATA\Legal-Agent$\r$\n（管理者権限は不要です。Program Files には何も入りません）$\r$\n$\r$\n「次へ」を押すと、アプリ専用の Python とライブラリをインターネットから取得します。回線によっては数分かかります。$\r$\n$\r$\n※ 既に導入済みの場合は上書き更新になります。API キー・索引・調査履歴はそのまま残ります。"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_TITLE "導入が完了しました"
!define MUI_FINISHPAGE_TEXT "デスクトップの「Legal-Agent」からいつでも起動できます。$\r$\n$\r$\n初回はブラウザの設定画面で Anthropic の API キーを貼り付け、書籍 PDF のフォルダを選んでください。"
!define MUI_FINISHPAGE_NOAUTOCLOSE
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Japanese"

Section "Install"
  SetOutPath "$INSTDIR"
  DetailPrint "アプリのファイルを配置しています..."
  File /r "${PAYLOAD}\*"

  ; 更新のときは、古いコードで動いているサーバーを止めてから導入し直す
  DetailPrint "起動中の Legal-Agent があれば停止しています..."
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\stop.ps1" -Quiet'
  Pop $0

  ; 「アプリと機能」に載せる（HKCU なので管理者権限は不要）
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${DISPLAY_VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\legal_agent\static\legal-agent.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Python とライブラリの導入・ショートカット作成・起動は install.ps1 に任せる
  DetailPrint "アプリ専用の Python とライブラリを導入しています（数分かかります）..."
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\install.ps1"'
  Pop $0
  DetailPrint "install.ps1 の終了コード: $0"

  ; 使用量の目安を「アプリと機能」に出す
  ${GetSize} "$INSTDIR" "/S=0K" $1 $2 $3
  IntFmt $1 "0x%08X" $1
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$1"
SectionEnd

Section "Uninstall"
  DetailPrint "起動中の Legal-Agent を停止しています..."
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\stop.ps1" -Quiet'
  Pop $0
  Sleep 1500

  ; アプリ本体と、導入時に作られたもの
  RMDir /r "$INSTDIR\legal_agent"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\logs"
  RMDir /r "$INSTDIR\legal_agent.egg-info"
  Delete "$INSTDIR\*.bat"
  Delete "$INSTDIR\*.ps1"
  Delete "$INSTDIR\*.sh"
  Delete "$INSTDIR\pyproject.toml"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\.env.example"
  Delete "$INSTDIR\.gitattributes"
  Delete "$INSTDIR\.gitignore"
  Delete "$INSTDIR\.update.json"
  Delete "$INSTDIR\uninstall.exe"

  ; デスクトップのショートカット（OneDrive にリダイレクトされている場合も見る）
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$PROFILE\Desktop\${APP_NAME}.lnk"

  ; API キーと索引・履歴は取り戻せないので、消すかどうか必ず尋ねる（既定は残す）
  IfSilent uninst_keep_data
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 \
    "設定（Anthropic API キー）と、書籍の索引・調査履歴も削除しますか？$\r$\n$\r$\n「いいえ」を選ぶと $INSTDIR に残し、次に入れ直したときそのまま使えます。$\r$\n「はい」を選ぶと消えます（書籍の索引は作り直しになります）。" \
    IDNO uninst_keep_data
  RMDir /r "$INSTDIR\data"
  Delete "$INSTDIR\.env"
uninst_keep_data:

  DeleteRegKey HKCU "${UNINST_KEY}"
  ; 中身が残っていなければフォルダも消す（.env / data を残した場合は残る）
  RMDir "$INSTDIR"
SectionEnd
