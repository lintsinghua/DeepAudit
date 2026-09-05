import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '../serverClient';
import { fetchAllPages, fetchPage } from '../pagination';
vi.mock('../serverClient', () => ({ apiClient: { get: vi.fn() } }));
beforeEach(() => vi.resetAllMocks());
describe('paged API', () => {
  it('uses server totals and forwards filters', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: [1], headers: {'x-total-count': '205'} });
    expect(await fetchPage('/tasks/', {skip: 20, limit: 20, status: 'running'})).toEqual({items: [1], total: 205});
    expect(apiClient.get).toHaveBeenCalledWith('/tasks/', {params: {skip: 20, limit: 20, status: 'running'}});
  });
  it('exports every page without truncating at the default limit', async () => {
    const first = Array.from({length: 100}, (_, i) => i);
    vi.mocked(apiClient.get).mockResolvedValueOnce({data: first}).mockResolvedValueOnce({data: [100, 101]});
    expect(await fetchAllPages('/findings', {severity: 'high'})).toEqual([...first, 100, 101]);
    expect(apiClient.get).toHaveBeenLastCalledWith('/findings', {params: {severity: 'high', skip: 100, limit: 100}});
  });
  it('does not publish a partial export after a later page fails', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({data: Array(100).fill(1)}).mockRejectedValueOnce(new Error('offline'));
    await expect(fetchAllPages('/issues')).rejects.toThrow('offline');
  });
});
