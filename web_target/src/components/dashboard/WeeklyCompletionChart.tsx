import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import './WeeklyCompletionChart.css';

// Mock data for the chart
const data = [
  { name: 'Mon', completed: 4 },
  { name: 'Tue', completed: 6 },
  { name: 'Wed', completed: 5 },
  { name: 'Thu', completed: 8 },
  { name: 'Fri', completed: 7 },
  { name: 'Sat', completed: 3 },
  { name: 'Sun', completed: 9 },
];

const WeeklyCompletionChart: React.FC = () => {
  const mostProductiveDay = data.reduce((prev, current) => (prev.completed > current.completed) ? prev : current);

  return (
    <div className="weekly-chart-container">
      <ResponsiveContainer width="100%" height={300}>
        <BarChart
          data={data}
          margin={{
            top: 20,
            right: 30,
            left: 20,
            bottom: 5,
          }}
        >
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" />
          <YAxis />
          <Tooltip />
          <Legend />
          <Bar dataKey="completed" fill="#8884d8" name="Completed Tasks" />
        </BarChart>
      </ResponsiveContainer>
      <div className="chart-summary">
        <p>Your most productive day was <strong>{mostProductiveDay.name}</strong> with <strong>{mostProductiveDay.completed}</strong> tasks completed!</p>
      </div>
    </div>
  );
};

export default WeeklyCompletionChart;
