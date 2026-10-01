import React from 'react';
import WeeklyCompletionChart from '../components/dashboard/WeeklyCompletionChart';
import './DashboardPage.css';

const DashboardPage: React.FC = () => {
  return (
    <div className="dashboard-page">
      <header className="dashboard-header">
        <h1>Dashboard</h1>
        <p>Welcome back! Here's your weekly productivity overview.</p>
      </header>
      <main className="dashboard-main">
        <section className="chart-section">
          <h2>Weekly Task Completions</h2>
          <WeeklyCompletionChart />
        </section>
        {/* Other dashboard widgets will go here */}
      </main>
    </div>
  );
};

export default DashboardPage;
