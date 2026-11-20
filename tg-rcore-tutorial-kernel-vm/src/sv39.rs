//! 教学内核低半区的 Sv39 匿名映射。

use crate::{AddressSpace, PageManager};
use core::ops::Range;
use page_table::{VPN, VmFlags, VmMeta};

/// Sv39 教学内核用户地址的排他上界。
pub const USER_END: usize = 1 << 38;

fn user_pages<Meta: VmMeta>(addr: usize, len: usize) -> Option<Range<VPN<Meta>>> {
    const PAGE_SIZE: usize = 4096;
    if addr >= USER_END || !addr.is_multiple_of(PAGE_SIZE) {
        return None;
    }
    let start = addr / PAGE_SIZE;
    let end = start.checked_add(len.div_ceil(PAGE_SIZE))?;
    (end <= USER_END / PAGE_SIZE).then(|| VPN::new(start)..VPN::new(end))
}

/// 在使用 Sv39 页表元数据的地址空间中建立零填充的匿名映射。
pub fn mmap<Meta: VmMeta, M: PageManager<Meta>>(
    space: &mut AddressSpace<Meta, M>,
    addr: usize,
    len: usize,
    prot: i32,
) -> bool {
    let Some(range) = user_pages(addr, len) else {
        return false;
    };
    if prot == 0 || prot & !0x7 != 0 {
        return false;
    }
    // SAFETY: 0x11 设置 Sv39 的 U/V 位，prot 的三位移至 R/W/X。
    let flags = unsafe { VmFlags::from_raw(0x11 | ((prot as usize) << 1)) };
    space.try_map_zeroed(range, flags)
}

/// 撤销 Sv39 用户映射。整个范围已映射且用户可访问时才修改页表。
pub fn munmap<Meta: VmMeta, M: PageManager<Meta>>(
    space: &mut AddressSpace<Meta, M>,
    addr: usize,
    len: usize,
) -> bool {
    let Some(range) = user_pages(addr, len) else {
        return false;
    };
    // SAFETY: 0x11 只设置 Sv39 的 U/V 位。
    let user = unsafe { VmFlags::from_raw(0x11) };
    if (range.start.val()..range.end.val())
        .any(|page| space.translate::<u8>(VPN::new(page).base(), user).is_none())
    {
        return false;
    }
    if range.start != range.end {
        space.unmap(range);
    }
    true
}
