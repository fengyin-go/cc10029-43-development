/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
  /** 教学成果申报专用：开启送审材料包导出/凭包受理流程 */
  packageFlow?: boolean
}

/** 送审材料包视图：评审员打开上报单时看到的包状态与材料快照 */
export type AwardPackageView = {
  包编号: string
  成果ID: number
  成果名称: string
  状态: string
  失效原因: string
  导出时间: string
  受理时间: string
  可受理: boolean
  提示: string
  材料: {
    模块: string
    材料ID: number
    名称: string
    档案类型: string
    教师姓名: string
    导出时状态: string
  }[]
}

export type PackageResult = {
  ok: boolean
  message: string
  package: AwardPackageView | null
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}
