import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PackageResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

/** 教学成果申报：从已初审成果导出送审材料包（重复导出返回同一个包） */
export async function exportAwardPackage(id: number): Promise<PackageResult> {
  const response = await request(`/api/teach_award/${id}/package`, { method: 'POST' })
  return await response.json()
}

/** 教学成果申报：按包编号核验材料包能否受理，或查验已受理包当时的材料 */
export async function verifyAwardPackage(packageNo: string): Promise<PackageResult> {
  const response = await request(`/api/teach_award/packages/${encodeURIComponent(packageNo)}`)
  return await response.json()
}

/** 教学成果申报：评审员交回包编号后，凭包受理上报 */
export async function submitAwardWithPackage(
  id: number,
  packageNo: string,
): Promise<ActionResult> {
  const response = await request(`/api/teach_award/${id}/submit`, {
    method: 'POST',
    body: JSON.stringify({ package_no: packageNo }),
  })
  return await response.json()
}
