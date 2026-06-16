import type { ListingTargetOption } from '@/types'

export interface ListingTargetFamilyGroup {
  family_code: string
  options: ListingTargetOption[]
}

export function formatMaterialGroupTitle(item: ListingTargetOption): string {
  return `${item.family_code} · ${item.image_set}`
}

export function formatMaterialGroupLabel(item: ListingTargetOption): string {
  const listed = item.listed_count || 0
  const count = item.product_count || item.product_codes.length
  const unlisted = item.unlisted_count ?? Math.max(0, count - listed)
  const base = formatMaterialGroupTitle(item)
  if (item.is_material_ready === false && count === 0) return `${base} · 素材未就绪`
  if (item.is_fully_listed) return `${base} · 已全部上架`
  if (unlisted > 0) return `${base} · 待上架 ${unlisted}/${count}`
  if (listed > 0) return `${base} · 已上架 ${listed}/${count}`
  return `${base} · ${count} 个商品`
}

export function formatMaterialGroupMeta(item: ListingTargetOption): string {
  const count = item.product_count || item.product_codes.length
  if (item.is_material_ready === false && count === 0) {
    return '素材未就绪（目录为空或无编号主图）'
  }
  const unlisted = item.unlisted_count ?? Math.max(0, count - (item.listed_count || 0))
  if (item.is_fully_listed) return `${count} 个商品 · 已全部上架`
  if (unlisted > 0) return `${count} 个商品 · 待上架 ${unlisted}`
  if ((item.listed_count || 0) > 0) return `${count} 个商品 · 已上架 ${item.listed_count}/${count}`
  return `${count} 个商品`
}

export function groupListingTargetsByFamily(items: ListingTargetOption[]): ListingTargetFamilyGroup[] {
  const groups = new Map<string, ListingTargetOption[]>()
  for (const item of items) {
    const list = groups.get(item.family_code) ?? []
    list.push(item)
    groups.set(item.family_code, list)
  }
  return [...groups.entries()].map(([family_code, options]) => ({ family_code, options }))
}
