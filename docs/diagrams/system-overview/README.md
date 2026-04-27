# system-overview 다이어그램 (Mermaid 소스)

- **렌더 결과(PNG)**: `docs/images/system-overview/`
- **스타일**: `mermaid-frontend.json` — `base` 테마, 한글·여백·색 대비(프론트 UI 느낌). `mermaid-frontend.css` — 페이지 배경·흰 카드·둥근 모서리.
- **재생성 (PowerShell, `docs` 루트에서 실행)**:

```powershell
$cfg  = "diagrams\system-overview\mermaid-frontend.json"
$css  = "diagrams\system-overview\mermaid-frontend.css"
Get-ChildItem "diagrams\system-overview\*.mmd" | ForEach-Object {
  npx -y @mermaid-js/mermaid-cli@10.9.0 `
    -i $_.FullName `
    -o (Join-Path (Get-Location) "images\system-overview\$($_.BaseName).png") `
    -w 2200 -H 1500 -b "#e8edf3" -c (Join-Path (Get-Location) $cfg) -C (Join-Path (Get-Location) $css) -s 1.5
}
```

- `-b "#e8edf3"`: PNG 바깥 배경(앱 셸).
- `-s 1.5`: 해상도·글자 가독성(파일이 커지면 `1.25`~`1.5` 권장).
- `mmd`만 수정해도 되고, 톤을 바꾸려면 `mermaid-frontend.json` / `.css`를 조정한 뒤 다시 돌리면 된다.
