from pathlib import Path

root = Path(__file__).resolve().parent
changes = {
    'frontend/src/App.tsx': [
        ("const Dashboard = lazy", "const MarketScanner = lazy(() => import('@/pages/MarketScanner'))\nconst Dashboard = lazy"),
        ('<Route path="/dashboard"', '<Route path="/market-scanner" element={<MarketScanner />} />\n              <Route path="/dashboard"'),
    ],
    'frontend/src/config/navigation.ts': [
        ("export const navItems: NavItem[] = [", "export const navItems: NavItem[] = [\n  { href: '/market-scanner', label: 'Scanner', icon: TrendingUp },"),
    ],
    'blueprints/react_app.py': [
        ('# Scalping Terminal', '@react_bp.route("/market-scanner", strict_slashes=False)\ndef react_market_scanner():\n    return serve_react_app()\n\n\n# Scalping Terminal'),
    ],
    'frontend/vite.config.ts': [
        ('proxy: {', "proxy: {\n      '/market-scanner/api': {target: 'http://localhost:5000', changeOrigin: true},"),
    ],
}
for name, replacements in changes.items():
    path=root/name
    content=path.read_text(encoding='utf-8')
    for old,new in replacements:
        if new in content:
            continue
        if old not in content:
            raise ValueError(f'Missing integration anchor: {name}: {old}')
        content=content.replace(old,new,1)
    path.write_text(content,encoding='utf-8')
print('Isolated routes and navigation wired')
