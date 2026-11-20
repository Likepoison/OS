use tg_task_manage::stride::Stride;

#[test]
fn priority_changes_the_share_of_dispatches() {
    let mut tasks = [Stride::new(), Stride::new()];
    assert!(tasks[0].set_priority(4));
    assert!(tasks[1].set_priority(16));

    let mut dispatches = [0, 0];
    for _ in 0..500 {
        let (index, task) = tasks
            .iter_mut()
            .enumerate()
            .min_by_key(|(_, t)| t.total())
            .unwrap();
        task.charge();
        dispatches[index] += 1;
    }
    assert_eq!(dispatches, [100, 400]);
}

#[test]
fn invalid_priority_preserves_state_and_maximum_priority_makes_progress() {
    let mut task = Stride::new();
    assert!(!task.set_priority(1));
    assert!(!task.set_priority(-1));
    task.charge();
    assert_eq!(task.total(), (1 << 63) / 16);
    assert!(task.set_priority(isize::MAX));
    let before = task.total();
    task.charge();
    assert!(task.total() > before);
}
