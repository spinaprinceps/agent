import React from 'react';

interface FoodSelectionProps {
  options: string[];
  onSelect: (food: string) => void;
}

const FoodSelection: React.FC<FoodSelectionProps> = ({ options, onSelect }) => {
  if (!options || options.length === 0) return null;

  return (
    <div className="fs-wrap">
      <div className="fs-header">
        <span className="fs-icon">📸</span>
        <div>
          <div className="fs-title">Select Your Order</div>
          <div className="fs-sub">Tap a photo to proceed</div>
        </div>
      </div>

      <div className="fs-grid">
        {options.map((item) => (
          <div
            key={item}
            className="fs-img-card"
            onClick={() => onSelect(item)}
          >
            <img
              src={`https://via.placeholder.com/200x150?text=${encodeURIComponent(item)}`}
              alt={item}
              className="fs-img"
            />
            <div className="fs-img-label">{item.charAt(0).toUpperCase() + item.slice(1)}</div>
          </div>
        ))}
      </div>

      <style>{`
        .fs-wrap {
          background: #1a1a2e;
          border-radius: 20px;
          border: 1px solid rgba(255,255,255,0.1);
          padding: 20px;
          margin-top: 15px;
          animation: slideUp 0.4s cubic-bezier(0.16, 1, 0.3, 1);
        }
        @keyframes slideUp {
          from { opacity:0; transform:translateY(20px); }
          to   { opacity:1; transform:translateY(0); }
        }
        .fs-header {
          display: flex; align-items: center; gap: 14px;
          margin-bottom: 20px;
        }
        .fs-icon { font-size: 2rem; }
        .fs-title { font-size: 1.1rem; font-weight: 800; color: #fff; }
        .fs-sub { font-size: 0.8rem; color: #94a3b8; }

        .fs-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
          gap: 15px;
        }
        .fs-img-card {
          background: #252545;
          border-radius: 12px;
          overflow: hidden;
          cursor: pointer;
          transition: all 0.3s ease;
          border: 2px solid transparent;
        }
        .fs-img-card:hover {
          transform: translateY(-5px);
          border-color: #7c3aed;
          box-shadow: 0 10px 20px rgba(124, 58, 237, 0.2);
        }
        .fs-img {
          width: 100%;
          height: 100px;
          object-fit: cover;
          display: block;
        }
        .fs-img-label {
          padding: 10px;
          font-size: 0.85rem;
          font-weight: 700;
          text-align: center;
          color: #fff;
          background: rgba(0,0,0,0.2);
        }
      `}</style>
    </div>
  );
};

export default FoodSelection;
