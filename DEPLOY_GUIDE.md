# 🌐 외부 인터넷 배포 가이드

## 🎯 현재 상태 (Quick Tunnel 방식)

✅ **즉시 외부 접속 가능**
- URL: 매 실행마다 자동 발급 (예: `https://abc-xyz.trycloudflare.com`)
- 발급된 URL은 `tunnel.log` 또는 `show_url.bat` 실행 시 확인
- DB는 사용자 PC에 안전하게 보관 (절대 이동 안 함)
- HTTPS 자동 적용
- 무료, 무제한 트래픽

### ⚠️ Quick Tunnel 제약
| 항목 | 상태 |
|---|---|
| 접속 가능 | ✅ 어디서든 (스마트폰/외부 PC/회사 PC) |
| HTTPS | ✅ 자동 적용 |
| URL 영구성 | ⚠️ **PC 재부팅 / cloudflared 재시작 시 URL 변경** |
| 가동 시간 | ⚠️ 무보장 (실제로는 안정적이지만 SLA 없음) |
| 사용량 | 무제한 |

PC를 24/7 켜두면 URL이 안 바뀝니다. 재부팅하면 새 URL이 발급됩니다.

---

## 🚀 사용법

### 매일 사용
1. **run.bat** 더블클릭 → Streamlit + Cloudflare Tunnel 동시 실행
2. 콘솔 창에 표시되는 `https://...trycloudflare.com` URL 확인
3. URL 복사해서 사용

### URL 다시 확인하고 싶을 때
- **show_url.bat** 더블클릭

---

## 🎖 영구 URL로 업그레이드 (선택)

매번 URL이 바뀌는 게 싫으면 **Named Tunnel**로 업그레이드 가능합니다.
요건:
1. **Cloudflare 계정 (무료)**
2. **도메인 (선택)**
   - 본인 도메인: $10/년 (가비아, GoDaddy 등)
   - 무료 도메인: freenom.com 등 (안정성 떨어짐)
   - 또는 Cloudflare에서 도메인 구매 (.com $9.77/년)

### 업그레이드 단계
1. https://dash.cloudflare.com 회원가입
2. 도메인 등록 (또는 보유 도메인 Cloudflare로 이전)
3. 터미널에서:
   ```cmd
   cd "C:\Users\User\OneDrive\바탕 화면\판매분석앱"
   tools\cloudflared.exe login
   tools\cloudflared.exe tunnel create mga-sales
   tools\cloudflared.exe tunnel route dns mga-sales sales.yourdomain.com
   ```
4. 설정 파일 `~/.cloudflared/config.yml` 작성:
   ```yaml
   tunnel: mga-sales
   credentials-file: C:\Users\User\.cloudflared\<tunnel-uuid>.json
   ingress:
     - hostname: sales.yourdomain.com
       service: http://localhost:8501
     - service: http_status:404
   ```
5. 실행:
   ```cmd
   tools\cloudflared.exe tunnel run mga-sales
   ```
6. 이제 `https://sales.yourdomain.com` 이 영구 URL.

---

## 🛡️ 보안 고려사항

**Quick Tunnel은 URL만 알면 누구나 접속 가능합니다.**
사외 노출이 부담스럽다면:
- **Cloudflare Zero Trust Access** 추가 (이메일 인증 / Google SSO 등)
- Cloudflare 대시보드 > Zero Trust > Applications 에서 Tunnel에 접근 정책 설정
- 회사 이메일 도메인만 허용 가능

---

## 🆘 문제 해결

### "URL이 안 보여요"
- run.bat 실행 후 10초 정도 기다리세요
- `tunnel.log` 파일을 메모장으로 열어서 "trycloudflare.com" 검색
- show_url.bat 실행

### "외부에서 접속 안 돼요"
- 터널 프로세스가 살아있는지 확인: 작업관리자 → cloudflared.exe
- 죽었으면 run.bat 다시 실행

### "URL을 누군가에게 알려주고 싶어요"
- run.bat 콘솔에서 URL 복사
- 카톡/슬랙/메일로 전달
- 받은 사람은 URL 클릭만 하면 접속

---

## 💾 데이터는?

- **DB 위치**: `C:\Users\User\OneDrive\바탕 화면\판매분석앱\sales.db` (이 PC에만 있음)
- **클라우드 미이동**: 외부에서 접속해도 DB는 그대로 PC에 있음 (안전)
- **자동 백업**: 매 업로드 시 `backup/` 폴더에 사본 생성, 최근 30개 유지
- **OneDrive 동기화**: 폴더가 OneDrive 안이라 클라우드까지 자동 백업
