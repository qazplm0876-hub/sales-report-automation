# 매출실적 분석 자동화

월별 사업계획대비 매출실적 분석 보고서와 코멘트 초안을 생성하는 자동화 코드입니다.

## 현재 실행 방식

현재 버전은 기존 업무 폴더에 월별 원자료를 넣고 `monthly_report_final.py`의 `MONTH` 값을 수정한 뒤 실행합니다.

```powershell
python monthly_report_final.py
```

예를 들어 6월 실적 보고서를 작성할 때는 `monthly_report_final.py` 상단의 값을 아래처럼 바꿉니다.

```python
MONTH = 6
```

## 매월 준비할 파일

현재 스크립트와 같은 폴더에 아래 파일이 있어야 합니다.

- `사업계획대비_매출실적분석_26년_{N}월_.xlsx`
- `2026{N}월누계.xlsx` 또는 `.xls`
- `2025{N}월누계.xlsx` 또는 `.xls`
- `DSR_{N:02d}_상원.xlsx`
- `제강{N:02d}_상원.xlsx`
- `월별_사업계획.xlsx`
- `제품판매량_사업계획.xlsx`
- `2_해외현지내수판매계획_청도_비나_DCV_.xlsx`

수출 거래처 상세 파일은 아래 이름으로 준비합니다.

- `1.xlsx`: 합섬
- `2.xlsx`: 스텐
- `3.xlsx`: 제강

## 생성되는 파일

- `사업계획대비_매출실적분석_26년_{N}월_완성_CLAUDE.xlsx`
- `검증리포트_{N}월_CLAUDE.pdf`
- `코멘트_{N}월.md`

## GitHub 관리 원칙

이 저장소에는 자동화 코드, 설명서, 체크리스트, 이슈만 관리합니다.

실제 매출 원자료, 거래처 파일, 완성 엑셀, PDF 산출물은 민감 자료이므로 기본적으로 GitHub에 올리지 않습니다. `.gitignore`에서 엑셀/PDF 파일을 제외하도록 설정되어 있습니다.

## 향후 개선 방향

- `MONTH` 직접 수정 대신 `--month 6` 방식으로 실행
- 더블클릭 실행용 `run_monthly_report.bat` 추가
- 월별 `inputs/YYYY-MM`, `outputs/YYYY-MM` 폴더 구조 적용
- 보고서용 코멘트, 분석 근거, 사수/팀장 예상 질문 파일 분리 생성
- GitHub Issues로 개선 요청 관리

