use std::alloc::{Layout, alloc_zeroed, dealloc};
use std::ptr::NonNull;
use likepoison_proj20_kernel_vm::{
    AddressSpace, PageManager,
    page_table::{MmuMeta, PPN, Pte, VPN, VmFlags},
};

const PAGE_SIZE: usize = 4096;
const ALLOCATION_LIMIT: usize = 4;

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
struct TestSv39;

impl MmuMeta for TestSv39 {
    const P_ADDR_BITS: usize = 56;
    const PAGE_BITS: usize = 12;
    const LEVEL_BITS: &'static [usize] = &[9; 3];
    const PPN_POS: usize = 10;

    fn is_leaf(flags: usize) -> bool {
        flags & 0b1110 != 0
    }
}

struct TestPages {
    root: NonNull<Pte<TestSv39>>,
    blocks: Vec<(NonNull<u8>, Layout)>,
}

impl PageManager<TestSv39> for TestPages {
    fn new_root() -> Self {
        let mut pages = Self {
            root: NonNull::dangling(),
            blocks: Vec::new(),
        };
        let mut flags = VmFlags::ZERO;
        pages.root = pages.allocate(1, &mut flags).cast();
        pages
    }

    fn root_ptr(&self) -> NonNull<Pte<TestSv39>> {
        self.root
    }

    fn p_to_v<T>(&self, page: PPN<TestSv39>) -> NonNull<T> {
        NonNull::new(std::ptr::with_exposed_provenance_mut(
            page.val() * PAGE_SIZE,
        ))
        .unwrap()
    }

    fn v_to_p<T>(&self, ptr: NonNull<T>) -> PPN<TestSv39> {
        PPN::new(ptr.as_ptr().expose_provenance() / PAGE_SIZE)
    }

    fn check_owned(&self, pte: Pte<TestSv39>) -> bool {
        let ptr = self.p_to_v::<u8>(pte.ppn());
        self.blocks.iter().any(|(block, _)| *block == ptr)
    }

    fn allocate(&mut self, count: usize, flags: &mut VmFlags<TestSv39>) -> NonNull<u8> {
        self.try_allocate(count, flags).unwrap()
    }

    fn try_allocate(&mut self, count: usize, _: &mut VmFlags<TestSv39>) -> Option<NonNull<u8>> {
        if self.blocks.len() == ALLOCATION_LIMIT {
            return None;
        }
        let layout = Layout::from_size_align(count * PAGE_SIZE, PAGE_SIZE).unwrap();
        let block = NonNull::new(unsafe { alloc_zeroed(layout) })?;
        self.blocks.push((block, layout));
        Some(block)
    }

    fn deallocate(&mut self, pte: Pte<TestSv39>, count: usize) -> usize {
        let ptr = self.p_to_v::<u8>(pte.ppn());
        let pos = self
            .blocks
            .iter()
            .position(|(block, _)| *block == ptr)
            .unwrap();
        let (block, layout) = self.blocks.swap_remove(pos);
        assert_eq!(layout.size(), count * PAGE_SIZE);
        unsafe { dealloc(block.as_ptr(), layout) };
        count
    }

    fn drop_root(&mut self) {
        for (block, layout) in self.blocks.drain(..) {
            unsafe { dealloc(block.as_ptr(), layout) };
        }
    }
}

impl Drop for TestPages {
    fn drop(&mut self) {
        self.drop_root();
    }
}

#[test]
fn failed_second_page_rolls_back_and_allows_retry() {
    let mut space = AddressSpace::<TestSv39, TestPages>::new();
    let first = VPN::new(511);
    let flags = unsafe { VmFlags::from_raw(0b11) };

    // The second leaf needs another page table after the allocator reaches its limit.
    assert!(!space.try_map_zeroed(first..first + 2, flags));
    assert!(space.areas.is_empty());
    assert!(space.translate::<u8>(first.base(), flags).is_none());

    assert!(space.try_map_zeroed(first..first + 1, flags));
    let byte = space.translate::<u8>(first.base(), flags).unwrap();
    assert_eq!(unsafe { byte.as_ptr().read() }, 0);
    assert!(!space.try_map_zeroed(first..first + 1, flags));
    assert_eq!(space.translate::<u8>(first.base(), flags), Some(byte));
}
