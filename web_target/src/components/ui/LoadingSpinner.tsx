import React from 'react';

export const LoadingSpinner: React.FC<{ fullPage?: boolean }> = ({ fullPage }) => (
  <div style={{ padding: '20px', textAlign: 'center' }}>
    Loading...
  </div>
);
