# 시연 화면 ( demo_ui )

합성 시연 코퍼스 ( 스냅샷 900 ) 전용 화면이다. 실험 코퍼스 · 정답셋 · 평가 결과와 섞지 않는다.
보는 사람별 거르기는 시연 API 가 하고, 이 화면은 받은 것만 그린다.
"보는 사람 선택" 은 시연용 선택 화면이며 인증이 아니다.

## 실행 순서

1. 임베딩 서버를 띄운다 ( 시연 API 가 시작할 때 노트를 임베딩한다 )
2. 시연 API 를 띄운다. 화면 주소를 CORS 허용 출처로 준다

   ```
   python -m serve.demo_api --run-dir <완료된 제안 실행 폴더> --host 127.0.0.1 --port 8090 --cors-origin http://localhost:5173
   ```

3. 화면 의존성을 설치한다 ( package-lock.json 으로 버전 고정 )

   ```
   cd demo_ui
   npm ci
   ```

4. 화면을 띄운다 ( 포트 5173 고정 )

   ```
   npm run dev
   ```

API 주소는 `.env.development` 의 `VITE_API_BASE` 로만 받는다. 코드에 기본값이 없어서 값이 없으면 화면에 오류 문구가 나온다.

## 확인

```
npm run typecheck
npm test
npm run build
```
