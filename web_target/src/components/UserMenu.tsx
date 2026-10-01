import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import './UserMenu.css';

const UserMenu: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const menuRef = useRef<HTMLDivElement>(null);

  const handleToggle = () => setIsOpen(!isOpen);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  if (!user) {
    return null;
  }

  return (
    <div className="user-menu" ref={menuRef}>
      <button onClick={handleToggle} className="user-menu-trigger" aria-haspopup="true" aria-expanded={isOpen}>
        <img src={user.avatarUrl || 'https://i.pravatar.cc/40'} alt="User Avatar" className="avatar" />
        <span className="user-name">{user.name}</span>
        <svg className={`chevron ${isOpen ? 'open' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </button>
      {isOpen && (
        <div className="user-menu-dropdown" role="menu">
          <div className="dropdown-header">
            <p className="user-name-large">{user.name}</p>
            <p className="user-email">{user.email}</p>
          </div>
          <ul>
            <li role="presentation">
              <button onClick={() => navigate('/profile')} role="menuitem">프로필</button>
            </li>
            <li role="presentation">
              <button onClick={() => navigate('/settings')} role="menuitem">설정</button>
            </li>
            <li role="presentation">
              <button onClick={handleLogout} className="logout-btn" role="menuitem">로그아웃</button>
            </li>
          </ul>
        </div>
      )}
    </div>
  );
};

export default UserMenu;
