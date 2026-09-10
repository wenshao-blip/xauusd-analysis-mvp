import type { NextConfig } from 'next';

const repository = process.env.GITHUB_REPOSITORY?.split('/')[1] ?? '';
const onPages = process.env.GITHUB_ACTIONS === 'true';
const basePath = onPages && repository && !repository.endsWith('.github.io') ? `/${repository}` : '';
// Vinext must export the page at the artifact root for GitHub Pages. Only
// static asset URLs need the repository prefix.
const nextConfig: NextConfig = { output: 'export', assetPrefix: basePath };

export default nextConfig;
