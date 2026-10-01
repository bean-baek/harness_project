const express = require('express');
const path = require('path');
const app = express();
const PORT = process.env.PORT || 3001;

// 클라이언트 빌드 파일 제공
app.use(express.static(path.join(__dirname, '../client/build')));

// API 라우트
app.get('/api/data', (req, res) => {
  res.json({ message: 'Hello from server!' });
});

// 모든 요청을 클라이언트 앱으로 전달하여 React Router가 처리하도록 함
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, '../client/build', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`Server is running on port ${PORT}`);
});
