# system-overview 다이어그램 (Mermaid → Markdown)

- **렌더 결과(PNG)**: `docs/images/system-overview/`
- **소스**: `01-*.md` … `10-*.md` — 각 파일에 ` ```mermaid ` … ` ``` ` 블록으로 기술한다(GitHub 등에서 미리보기 가능).
- **스타일**: `mermaid-frontend.json` — `base` 테마, 한글·여백·색 대비(프론트 UI 느낌). `mermaid-frontend.css` — 페이지 배경·흰 카드·둥근 모서리.
- **재생성 (PowerShell, `docs` 루트에서 실행)**:

`mermaid-cli`는 **`.md` 안의 mermaid 코드 블록**을 추출해 PNG로 내보낸다.

```powershell
$cfg  = "diagrams\system-overview\mermaid-frontend.json"
$css  = "diagrams\system-overview\mermaid-frontend.css"
Get-ChildItem "diagrams\system-overview" -File | Where-Object { $_.Name -match '^\d{2}-.+\.md$' } | ForEach-Object {
  $base = $_.BaseName
  $outDir = Join-Path (Get-Location) "images\system-overview"
  npx -y @mermaid-js/mermaid-cli@10.9.0 `
    -i $_.FullName `
    -o (Join-Path $outDir "$base.png") `
    -w 2200 -H 1500 -b "#e8edf3" -c (Join-Path (Get-Location) $cfg) -C (Join-Path (Get-Location) $css) -s 1.5
  # Markdown 입력 시 CLI가 `이름-1.png`로 내보내는 경우가 있어 `이름.png`로 맞춘다.
  $wrong = Join-Path $outDir "$base-1.png"
  $right = Join-Path $outDir "$base.png"
  if (Test-Path $wrong) {
    if (Test-Path $right) { Remove-Item $right -Force }
    Move-Item -Force $wrong $right
  }
}
```

- `-b "#e8edf3"`: PNG 바깥 배경(앱 셸).
- `-s 1.5`: 해상도·글자 가독성(파일이 커지면 `1.25`~`1.5` 권장).
- 다이어그램 `.md`를 수정하거나, 톤을 바꾸려면 `mermaid-frontend.json` / `.css`를 조정한 뒤 다시 돌리면 된다.
