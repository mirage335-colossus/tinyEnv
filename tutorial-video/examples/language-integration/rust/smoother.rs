// A one-pole smoother. Use alpha in [0, 1]; the caller retains previous output.
pub fn apply(previous: f32, sample: f32, alpha: f32) -> f32 {
    previous + alpha * (sample - previous)
}
