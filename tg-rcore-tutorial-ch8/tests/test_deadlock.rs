extern crate alloc;

#[path = "../src/deadlock.rs"]
mod deadlock;

use deadlock::{Detector, Resources};

#[test]
fn rejects_self_lock_and_crossed_wait_but_preserves_state() {
    let mut detector = Detector::default();
    assert!(!detector.enabled);
    let resources = &mut detector.mutexes;
    resources.add(0, 1);
    resources.add(1, 1);
    resources.request(1, 0, true);
    assert!(resources.would_deadlock(1, 0));

    resources.request(2, 1, true);
    assert!(!resources.would_deadlock(1, 1));
    resources.request(1, 1, false);
    assert!(resources.would_deadlock(2, 0));

    resources.release(2, 1, Some(1), true);
    resources.release(1, 1, None, true);
    assert_eq!(resources.available(1), 1);
    assert!(!resources.would_deadlock(2, 1));

    detector.semaphores.add(0, 0);
    detector.remove_thread(1);
    assert!(!detector.mutexes.would_deadlock(1, 0));
}

#[test]
fn accepts_safe_order_and_external_signal() {
    let mut resources = Resources::default();
    resources.add(0, 0);
    resources.add(1, 2);
    assert!(!resources.would_deadlock(1, 0));
    resources.request(1, 0, false);
    resources.release(2, 0, Some(1), false);
    assert_eq!(resources.available(0), 0);

    resources.request(2, 1, true);
    resources.request(3, 1, true);
    assert!(!resources.would_deadlock(1, 1));
    resources.request(1, 1, false);
    resources.release(3, 1, Some(1), false);
    resources.release(1, 1, None, false);
    assert_eq!(resources.available(1), 1);
}
