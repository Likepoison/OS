//! Stride 调度计数。每次选中进程后按优先级累加步长。

const BIG_STRIDE: u128 = 1 << 63;
const DEFAULT_PRIORITY: usize = 16;

pub(super) struct Stride {
    priority: usize,
    total: u128,
}

impl Stride {
    pub(super) const fn new() -> Self {
        Self {
            priority: DEFAULT_PRIORITY,
            total: 0,
        }
    }

    pub(super) fn total(&self) -> u128 {
        self.total
    }

    pub(super) fn set_priority(&mut self, priority: isize) -> bool {
        if priority < 2 {
            return false;
        }
        self.priority = priority as usize;
        true
    }

    pub(super) fn charge(&mut self) {
        let step = BIG_STRIDE / self.priority as u128;
        self.total = self
            .total
            .checked_add(step)
            .expect("stride counter exhausted");
    }
}
