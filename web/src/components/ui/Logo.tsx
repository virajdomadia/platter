// The Platter mark in the Bento palette: a violet plate with a coral pin.
export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true">
      <rect width="64" height="64" rx="18" fill="#E6DEFF" />
      <circle cx="30" cy="34" r="20" fill="#7B5CFF" />
      <circle cx="30" cy="34" r="12.5" fill="#F3F0FF" />
      <circle cx="30" cy="34" r="6.5" fill="#7B5CFF" />
      <path d="M45 8c5.5 0 9 3.6 9 8.2 0 6.4-9 15.3-9 15.3s-9-8.9-9-15.3C36 11.6 39.5 8 45 8z" fill="#FF7A59" stroke="#F3F0FF" strokeWidth="2.5" />
      <circle cx="45" cy="16.3" r="3.2" fill="#F3F0FF" />
    </svg>
  );
}
