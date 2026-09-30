//! Allocation-free population Bollinger moments for a short HA window.
//! Build: rustc --crate-type cdylib -O bands.rs -o libbands.dylib

#[unsafe(no_mangle)]
pub unsafe extern "C" fn ha_bands(values: *const f64, n: usize, out: *mut f64) -> i32 {
    if values.is_null() || out.is_null() || n == 0 || n > 20 { return 0; }
    let data = unsafe { std::slice::from_raw_parts(values, n) };
    if data.iter().any(|x| !x.is_finite()) { return 0; }
    let mean = data.iter().sum::<f64>() / n as f64;
    let variance = data.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / n as f64;
    unsafe { *out = mean; *out.add(1) = mean + 2.0 * variance.sqrt(); }
    1
}

#[cfg(test)]
mod tests {
    #[test]
    fn population_variance() {
        let data = [1.0, 2.0, 3.0]; let mut out = [0.0; 2];
        assert_eq!(unsafe { super::ha_bands(data.as_ptr(), 3, out.as_mut_ptr()) }, 1);
        assert_eq!(out[0], 2.0);
        assert!((out[1] - (2.0 + 2.0 * (2.0_f64/3.0).sqrt())).abs() < 1e-12);
    }
}
