const FIELD_LABELS = {
  time: '时间(秒)',
  temperature: '温度(°C)',
  points: '采样点',
  probe: '双探头',
  probeA: '探头A',
  probeB: '探头B',
  probeC: '探头C',
  body: '请求体',
};

export function fieldLabel(field) {
  return FIELD_LABELS[field] ?? field ?? '请求';
}

export function formatMinutes(value, digits = 2) {
  return Number(value).toFixed(digits);
}
