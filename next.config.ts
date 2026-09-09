import type { NextConfig } from 'next';

const repository = process.env.GITHUB_REPOSITORY?.split('/')[1] ?? '';
const onPages = process.env.GITHUB_ACTIONS === 'true';
const basePath = onPages && repository && !repository.endsWith('.github.io') ? `/${repository}` : '';
const nextConfig: NextConfig = { output: 'export', basePath, assetPrefix: basePath };

export default nextConfig;
