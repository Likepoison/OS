//! 每个进程独立维护互斥锁和信号量的可用量、占用量及等待项。

use alloc::{
    collections::{BTreeMap, BTreeSet},
    vec::Vec,
};

#[derive(Default)]
pub(super) struct Detector {
    pub(super) enabled: bool,
    pub(super) mutexes: Resources,
    pub(super) semaphores: Resources,
}

impl Detector {
    pub(super) fn remove_thread(&mut self, tid: usize) {
        // 原语的资源释放语义独立于退出。已经退出的线程不能使安全序列继续。
        self.mutexes.threads.remove(&tid);
        self.semaphores.threads.remove(&tid);
    }
}

#[derive(Default)]
pub(super) struct Resources {
    available: Vec<usize>,
    threads: BTreeMap<usize, ThreadState>,
}

#[derive(Default)]
struct ThreadState {
    holding: BTreeMap<usize, usize>,
    waiting: Option<usize>,
}

impl Resources {
    pub(super) fn add(&mut self, resource: usize, available: usize) {
        assert_eq!(resource, self.available.len());
        self.available.push(available);
    }

    pub(super) fn available(&self, resource: usize) -> usize {
        self.available[resource]
    }

    pub(super) fn would_deadlock(&self, tid: usize, resource: usize) -> bool {
        // 当前可立即满足的请求不会新增等待。无持有量的线程也不会形成资源环。
        if self.available[resource] != 0
            || self
                .threads
                .get(&tid)
                .is_none_or(|thread| thread.holding.is_empty())
        {
            return false;
        }

        let mut work = self.available.clone();
        let mut finished = BTreeSet::new();
        loop {
            let mut progressed = false;
            for (&candidate, thread) in &self.threads {
                let need = if candidate == tid {
                    Some(resource)
                } else {
                    thread.waiting
                };
                if finished.contains(&candidate) || need.is_some_and(|id| work[id] == 0) {
                    continue;
                }
                if candidate == tid {
                    return false;
                }
                finished.insert(candidate);
                for (&id, &held) in &thread.holding {
                    work[id] = work[id].saturating_add(held);
                }
                progressed = true;
            }
            if !progressed {
                return true;
            }
        }
    }

    pub(super) fn request(&mut self, tid: usize, resource: usize, acquired: bool) {
        let thread = self.threads.entry(tid).or_default();
        assert!(thread.waiting.is_none());
        if acquired {
            self.available[resource] -= 1;
            *thread.holding.entry(resource).or_default() += 1;
        } else {
            thread.waiting = Some(resource);
        }
    }

    pub(super) fn release(
        &mut self,
        tid: usize,
        resource: usize,
        recipient: Option<usize>,
        mutex: bool,
    ) {
        let owner = if mutex {
            self.threads
                .values_mut()
                .find(|thread| thread.holding.contains_key(&resource))
        } else {
            // 信号量的 up 也可由未持有该资源的线程发出。
            self.threads.get_mut(&tid)
        };
        if let Some(owner) = owner
            && let Some(count) = owner.holding.get_mut(&resource)
        {
            *count -= 1;
            if *count == 0 {
                owner.holding.remove(&resource);
            }
        }
        if let Some(waiter) = recipient {
            let thread = self
                .threads
                .get_mut(&waiter)
                .expect("queued resource waiter");
            assert_eq!(thread.waiting.take(), Some(resource));
            *thread.holding.entry(resource).or_default() += 1;
        } else {
            self.available[resource] += 1;
        }
    }
}
