export const EXERCISES = {
  squat: { name: '深蹲', group: '下肢', camera: '侧面', hint: '侧面全身入画，髋膝踝可见，先站直再下蹲。', family: 'knee', met: [3.5, 5] as const, rest: 1.3, id: '02050' },
  lunge: { name: '弓步', group: '下肢', camera: '侧面', hint: '侧面，前后分腿，前膝弯曲再蹬回。', family: 'split', met: [3.8, 5.5] as const, rest: 1.4, id: '02050' },
  side_lunge: { name: '侧弓步', group: '下肢', camera: '正面', hint: '正面，向一侧迈步下蹲再收回。', family: 'side_split', met: [3.8, 5.5] as const, rest: 1.4, id: '02050' },
  jumping_squat: { name: '跳蹲', group: '下肢', camera: '侧面', hint: '侧面，下蹲后向上跳起，落地再蹲。', family: 'knee_jump', met: [8, 10] as const, rest: 1.8, id: '02120' },
  calf_raise: { name: '提踵', group: '下肢', camera: '侧面', hint: '膝盖伸直，脚跟上提再放下。', family: 'bounce', met: [3, 4] as const, rest: 1.3, id: '02101' },
  deadlift: { name: '硬拉/髋铰链', group: '下肢', camera: '侧面', hint: '侧面，膝盖微屈，臀部后推再站直。', family: 'hinge', met: [5, 6] as const, rest: 1.5, id: '02054' },
  glute_bridge: { name: '臀桥', group: '下肢', camera: '侧面', hint: '仰卧，肩膀贴地，臀部上抬再放下。', family: 'bridge', met: [3.5, 5] as const, rest: 1.3, id: '02101' },
  hip_abduction: { name: '侧抬腿', group: '下肢', camera: '正面', hint: '正面站立，一侧腿向外抬起再收回。', family: 'side_leg', met: [3, 4.5] as const, rest: 1.3, id: '02101' },
  wall_sit: { name: '靠墙静蹲', group: '下肢', camera: '侧面', hint: '靠墙屈膝保持，每 8 秒计 1 次。', family: 'hold_squat', met: [3.5, 5] as const, rest: 1.5, id: '02050' },
  push_up: { name: '俯卧撑', group: '上肢', camera: '侧面', hint: '侧面，身体一条线，胸部靠近地面再撑起。', family: 'push', met: [6, 8] as const, rest: 1.6, id: '02054' },
  pull_up: { name: '引体向上', group: '上肢', camera: '正面抓杠', hint: '正面抓杠，按躯干相对手腕升降计数。', family: 'vertical_pull', met: [8, 9.8] as const, rest: 1.8, id: '02054' },
  dip: { name: '双杠臂屈伸', group: '上肢', camera: '侧面', hint: '手腕相对固定，身体下降再撑起。', family: 'dip', met: [8, 9] as const, rest: 1.7, id: '02054' },
  biceps_curl: { name: '弯举', group: '上肢', camera: '侧面', hint: '上臂贴身，屈肘把前臂抬起再放下。', family: 'curl', met: [3, 5] as const, rest: 1.3, id: '02054' },
  overhead_press: { name: '推举', group: '上肢', camera: '正面', hint: '手腕从肩上推过头顶再回到肩。', family: 'press', met: [3.5, 6] as const, rest: 1.4, id: '02050' },
  lateral_raise: { name: '侧平举', group: '上肢', camera: '正面', hint: '双手从体侧平举到肩高再放下。', family: 'raise_side', met: [3, 4.5] as const, rest: 1.3, id: '02050' },
  front_raise: { name: '前平举', group: '上肢', camera: '侧面', hint: '双手向前平举到肩高再放下。', family: 'raise_front', met: [3, 4.5] as const, rest: 1.3, id: '02050' },
  tricep_extension: { name: '臂屈伸', group: '上肢', camera: '侧面', hint: '手在头顶，屈肘下放再伸直。', family: 'tricep', met: [3, 4.5] as const, rest: 1.3, id: '02054' },
  bent_over_row: { name: '俯身划船', group: '上肢', camera: '侧面', hint: '髋铰链俯身，肘向后拉再伸直。', family: 'row', met: [4, 6] as const, rest: 1.4, id: '02054' },
  sit_up: { name: '仰卧起坐', group: '核心', camera: '侧面', hint: '仰卧，肩离开地面坐起再躺下。', family: 'sit', met: [3.8, 8] as const, rest: 1.4, id: '02171' },
  crunch: { name: '卷腹', group: '核心', camera: '侧面', hint: '仰卧，肩略离地，幅度小于仰卧起坐。', family: 'crunch', met: [2.8, 3.8] as const, rest: 1.3, id: '02171' },
  plank: { name: '平板支撑', group: '核心', camera: '侧面', hint: '身体一条线支撑，每保持 8 秒计 1 次。', family: 'hold_plank', met: [3.3, 4.5] as const, rest: 1.5, id: '02171' },
  mountain_climber: { name: '登山者', group: '核心', camera: '侧面', hint: '俯撑，双膝交替靠近胸口。', family: 'climber', met: [8, 10] as const, rest: 1.7, id: '02130' },
  russian_twist: { name: '俄罗斯转体', group: '核心', camera: '正面', hint: '坐姿，肩线左右转动。', family: 'twist', met: [3.5, 5] as const, rest: 1.3, id: '02171' },
  jumping_jack: { name: '开合跳', group: '有氧', camera: '正面', hint: '正面，手脚同时打开再同时收回。', family: 'open_close', met: [7, 8.3] as const, rest: 1.5, id: '02022' },
  jump_rope: { name: '跳绳', group: '有氧', camera: '正面或侧面', hint: '连续小跳，手腕在腰侧摇绳。', family: 'rope', met: [8.8, 12.3] as const, rest: 1.8, id: '15552' },
  high_knees: { name: '高抬腿', group: '有氧', camera: '正面', hint: '交替把膝盖抬过髋部。', family: 'high_knee', met: [8, 10] as const, rest: 1.7, id: '12020' },
  running_in_place: { name: '原地跑', group: '有氧', camera: '正面', hint: '小步交替抬膝，不必高过髋。', family: 'jog', met: [6, 8] as const, rest: 1.6, id: '12020' },
  burpee: { name: '波比跳', group: '有氧', camera: '侧面', hint: '下蹲撑地、蹬回、再跳起。', family: 'burpee', met: [8, 11] as const, rest: 1.8, id: '02130' },
  boxing: { name: '空击/出拳', group: '有氧', camera: '正面', hint: '左右手交替向前出拳再收回。', family: 'punch', met: [7.8, 10] as const, rest: 1.6, id: '12050' },
  arm_circle: { name: '绕臂', group: '有氧', camera: '正面', hint: '双臂绕肩画圈，每圈计 1 次。', family: 'circle', met: [2.8, 4] as const, rest: 1.3, id: '02050' },
} as const;

export type Exercise = keyof typeof EXERCISES;
export const EXERCISE_IDS = Object.keys(EXERCISES) as Exercise[];
export const EXERCISE_GROUPS = ['下肢', '上肢', '核心', '有氧'] as const;

export function isExercise(value: string): value is Exercise {
  return value in EXERCISES;
}

export function exerciseLabel(id: Exercise) {
  const item = EXERCISES[id];
  return `${item.name} · ${item.camera}`;
}
