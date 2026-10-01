const express = require('express');
const bodyParser = require('body-parser');
const app = express();
const port = 3001;

app.use(bodyParser.json());

// Mock Login
app.post('/api/auth/login', (req, res) => {
  const { email, password } = req.body;
  if (email === 'test@example.com' && password === 'SecurePass123!') {
    return res.json({
      token: 'mock-jwt-token',
      user: { id: '1', name: '홍길동', email: 'test@example.com', isAdmin: true }
    });
  }
  return res.status(401).json({ message: '이메일 또는 비밀번호가 올바르지 않습니다.' });
});

// Mock Logout
app.post('/api/auth/logout', (req, res) => {
  // In a real application, you would invalidate the token here.
  // For a mock server, we just need to acknowledge the request.
  console.log('User logged out');
  return res.status(200).json({ message: '성공적으로 로그아웃되었습니다.' });
});


// Mock Me
app.get('/api/auth/me', (req, res) => {
  res.json({ id: '1', name: '홍길동', email: 'test@example.com', isAdmin: true });
});

// Mock Dashboard Metrics
app.get('/api/dashboard/metrics', (req, res) => {
  res.json({
    totalUsers: 1250,
    monthlyRevenue: 4500000,
    activeSessions: 85,
    newSignups: 12
  });
});

app.listen(port, () => {
  console.log(`Mock API server running at http://localhost:${port}`);
});
