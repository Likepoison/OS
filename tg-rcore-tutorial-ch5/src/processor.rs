//! 处理器管理模块
//!
//! 定义 `PROCESSOR` 全局变量和 `ProcManager` 进程管理器。
//!
//! ## 设计思路
//!
//! 进程管理分为两部分：
//! - `PROCESSOR`：封装 `PManager`，提供全局访问接口，管理当前运行的进程
//! - `ProcManager`：实现 `Manage` 和 `Schedule` trait，负责进程的存储和调度
//!
//! ## 调度算法
//!
//! 从就绪队列选取累计 stride 最小的进程，同值时按进队顺序。
//! 发放一次运行机会后，对选中进程按优先级增加 stride。
//!
//! 教程阅读建议：
//!
//! - 先看 `ProcManager`：理解“存储结构(BTreeMap) + 调度结构(VecDeque)”双结构搭配；
//! - 再看 `Manage` 与 `Schedule` trait：理解抽象层如何为后续替换调度算法留接口；
//! - 最后结合 `ch5/src/main.rs` 中对 `PROCESSOR` 的调用观察状态流转。

use crate::process::Process;
use alloc::collections::{BTreeMap, VecDeque};
use core::cell::UnsafeCell;
use tg_task_manage::{Manage, PManager, ProcId, Schedule};

/// 处理器全局管理器
///
/// 封装 `PManager<Process, ProcManager>`，通过 `UnsafeCell` 提供内部可变性。
/// 在单核环境下是安全的，因为不会出现并发访问。
pub struct Processor {
    inner: UnsafeCell<PManager<Process, ProcManager>>,
}

unsafe impl Sync for Processor {}

impl Processor {
    /// 创建新的处理器管理器（编译期常量初始化）
    pub const fn new() -> Self {
        Self {
            inner: UnsafeCell::new(PManager::new()),
        }
    }

    /// 获取内部 PManager 的可变引用
    #[inline]
    pub fn get_mut(&self) -> &mut PManager<Process, ProcManager> {
        unsafe { &mut (*self.inner.get()) }
    }
}

/// 全局处理器管理器实例
pub static PROCESSOR: Processor = Processor::new();

/// 进程管理器
///
/// 负责管理所有进程实体和调度队列：
/// - `tasks`：以 ProcId 为键的进程映射表，存储所有进程实体
/// - `ready_queue`：就绪队列，存储等待执行的进程 PID
///
/// 就绪队列按 stride 取出任务，并用进队顺序处理并列。
pub struct ProcManager {
    /// 所有进程实体的映射表
    tasks: BTreeMap<ProcId, Process>,
    /// 就绪队列（进队顺序）
    ready_queue: VecDeque<ProcId>,
}

impl ProcManager {
    /// 创建新的进程管理器
    pub fn new() -> Self {
        Self {
            tasks: BTreeMap::new(),
            ready_queue: VecDeque::new(),
        }
    }
}

/// 实现 Manage trait：进程实体的增删查
impl Manage<Process, ProcId> for ProcManager {
    /// 插入新进程到进程表
    #[inline]
    fn insert(&mut self, id: ProcId, task: Process) {
        self.tasks.insert(id, task);
    }

    /// 根据 PID 获取进程的可变引用
    #[inline]
    fn get_mut(&mut self, id: ProcId) -> Option<&mut Process> {
        self.tasks.get_mut(&id)
    }

    /// 从进程表中删除进程（回收资源）
    #[inline]
    fn delete(&mut self, id: ProcId) {
        if let Some(process) = self.tasks.remove(&id) {
            // SAFETY: 当前已回到内核地址空间，此进程已经从就绪集合移除。
            unsafe { process.address_space.release() };
        }
    }
}

/// 实现 Schedule trait：按 stride 调度。
impl Schedule<ProcId> for ProcManager {
    /// 将进程加入就绪队列尾部
    fn add(&mut self, id: ProcId) {
        self.ready_queue.push_back(id);
    }

    /// 取出累计 stride 最小的进程，并计入这次调度。
    fn fetch(&mut self) -> Option<ProcId> {
        let (index, _) = self.ready_queue.iter().enumerate()
            .min_by_key(|(_, pid)| self.tasks[pid].stride.total())?;
        let pid = self.ready_queue.remove(index).expect("selected ready process");
        self.tasks.get_mut(&pid).expect("ready process exists").stride.charge();
        Some(pid)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tg_kernel_context::{foreign::ForeignContext, LocalContext};
    use tg_kernel_vm::AddressSpace;
    use tg_task_manage::stride::Stride;

    #[test]
    fn fetch_uses_stride_and_preserves_queue_order_on_a_tie() {
        let mut manager = ProcManager::new();
        let first = ProcId::new();
        let second = ProcId::new();
        for (pid, priority) in [(first, 4), (second, 16)] {
            let mut stride = Stride::new();
            assert!(stride.set_priority(priority));
            manager.insert(
                pid,
                Process {
                    pid,
                    stride,
                    context: ForeignContext {
                        context: LocalContext::empty(),
                        satp: 0,
                    },
                    address_space: AddressSpace::new(),
                    heap_bottom: 0,
                    program_brk: 0,
                },
            );
            manager.add(pid);
        }

        for expected in [first, second, second, second, second, first] {
            let selected = manager.fetch().unwrap();
            assert!(selected == expected);
            manager.add(selected);
        }
        assert!(manager.fetch() == Some(second));
        assert!(manager.fetch() == Some(first));
        assert!(manager.fetch().is_none());
        manager.delete(first);
        manager.delete(second);
    }
}
