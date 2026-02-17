'use client';

interface MenuWindowButtonProps {
  onClick: () => void;
  isOpen: boolean;
}

export function MenuWindowButton({ onClick, isOpen }: MenuWindowButtonProps) {
  return (
    <button
      onClick={onClick}
      className="fixed top-4 right-4 z-50 px-4 py-2 rounded-lg 
                 bg-black/60 backdrop-blur-md border border-white/10
                 text-white/80 text-sm font-medium
                 hover:bg-black/80 hover:border-white/20
                 transition-all duration-200
                 shadow-lg"
    >
      {isOpen ? 'Close Menu' : 'Menu Window'}
    </button>
  );
}
