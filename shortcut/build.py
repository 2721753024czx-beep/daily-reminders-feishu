"""Build an unsigned iPhone shortcut without including any credentials."""

import argparse
import plistlib
import re
import uuid
from pathlib import Path

TOKEN_PLACEHOLDER = "请填入飞书多维表格授权码"
RECORD_NOTE = "飞书记录："
COMPLETED_FIELD = "已完成"


def action(name, **params):
    return {
        "WFWorkflowActionIdentifier": f"is.workflow.actions.{name}",
        "WFWorkflowActionParameters": params,
    }


def output_action(name, output_name, **params):
    return action(name, UUID=str(uuid.uuid4()).upper(), CustomOutputName=output_name, **params)


def output_ref(source, as_text=False):
    params = source["WFWorkflowActionParameters"]
    ref = {
        "Type": "ActionOutput",
        "OutputUUID": params["UUID"],
        "OutputName": params["CustomOutputName"],
    }
    if as_text:
        ref["Aggrandizements"] = [{
            "Type": "WFCoercionVariableAggrandizement",
            "CoercionItemClass": "WFStringContentItem",
        }]
    return ref


def attachment(source, as_text=False):
    return {"WFSerializationType": "WFTextTokenAttachment", "Value": output_ref(source, as_text)}


def token_text(prefix="", source=None):
    value = {"string": prefix}
    if source is not None:
        position = len(prefix.encode("utf-16-le")) // 2
        value["string"] += "\uFFFC"
        value["attachmentsByRange"] = {f"{{{position}, 1}}": output_ref(source)}
    return {"WFSerializationType": "WFTextTokenString", "Value": value}


def item(key, value, item_type=0):
    return {"WFItemType": item_type, "WFKey": token_text(key), "WFValue": value}


def dictionary(*items):
    return {
        "WFSerializationType": "WFDictionaryFieldValue",
        "Value": {"WFDictionaryFieldValueItems": list(items)},
    }


def condition(source, when_true, otherwise=(), *, matches=None, contains=None):
    group = str(uuid.uuid4()).upper()
    comparison = {"WFCondition": 101} if matches is None else {
        "WFCondition": 4,
        "WFConditionalActionString": matches,
    }
    if contains is not None:
        comparison = {"WFCondition": 99, "WFConditionalActionString": contains}
    return [
        action("conditional", GroupingIdentifier=group, WFControlFlowMode=0,
               WFInput={"Type": "Variable", "Variable": attachment(source, as_text=True)},
               **comparison),
        *when_true,
        action("conditional", GroupingIdentifier=group, WFControlFlowMode=1),
        *otherwise,
        action("conditional", GroupingIdentifier=group, WFControlFlowMode=2),
    ]


def value(source, key, name=None):
    return output_action("getvalueforkey", name or key, WFInput=attachment(source),
                         WFGetDictionaryValueType="Value", WFDictionaryKey=key)


def request(name, credential, url, method, payload=None):
    params = {}
    if payload is not None:
        params = {"WFHTTPBodyType": "JSON", "WFJSONValues": payload}
    return output_action("downloadurl", name, WFURL=url, WFHTTPMethod=method,
                         WFHTTPHeaders=dictionary(item("Authorization", token_text("Bearer ", credential))),
                         **params)


def record_fields(*fields):
    nested = {"WFSerializationType": "WFDictionaryFieldValue", "Value": dictionary(*fields)}
    return dictionary(item("fields", nested, item_type=1))


def make_create_shortcut(endpoint):
    credential = output_action("gettext", "飞书授权码", WFTextActionText=TOKEN_PLACEHOLDER)
    title = output_action("ask", "任务标题", WFInputType="Text", WFAskActionPrompt="要做什么？")
    due = output_action("ask", "提醒时间", WFInputType="Date and Time", WFAskActionPrompt="什么时候提醒？")
    epoch = output_action("date", "Unix 起点", WFDateActionMode="Specified Date",
                          WFDateActionDate="1970-01-01T00:00:00Z")
    reminder = output_action("addnewreminder", "苹果提醒", WFCalendarItemTitle=token_text(source=title),
                      WFAlertEnabled="Alert", WFAlertCondition="At Time",
                      WFAlertCustomTime=token_text(source=due))
    seconds = output_action("gettimebetweendates", "截止秒数",
                            WFTimeUntilFromDate=token_text(source=epoch),
                            WFInput=token_text(source=due), WFTimeUntilUnit="Seconds")
    millis = output_action("math", "截止毫秒", WFInput=attachment(seconds),
                           WFMathOperation="×", WFMathOperand=1000)
    payload = record_fields(
        item("任务标题", token_text(source=title)),
        item("截止时间", token_text(source=millis), item_type=3),
    )
    post = request("飞书响应", credential, endpoint, "POST", payload)
    result = value(post, "code", "飞书返回码")
    data = value(post, "data")
    record = value(data, "record")
    record_id = value(record, "record_id", "飞书记录 ID")
    success = [
        data, record, record_id,
        action("setters.reminders", Mode="Set", WFInput=attachment(reminder),
               WFContentItemPropertyName="Notes",
               WFReminderContentItemNotes=token_text(RECORD_NOTE, record_id)),
        action("showresult", Text="苹果提醒已创建，任务已提交到飞书收件箱。"),
    ]

    actions = [
        action("comment", WFCommentActionText=(
            "将任务加到苹果提醒事项，并向飞书任务收件箱提交同样的标题和截止时间。"
            "导入后可在添加新提醒事项中选择每日必做清单。授权码只在自己的设备上填写。"
        )),
        credential,
        *condition(credential,
                   [action("showresult", Text="请先编辑快捷指令，填入这张飞书表的授权码。"), action("exit")],
                   matches=TOKEN_PLACEHOLDER),
        title,
        *condition(title, [action("showresult", Text="请输入任务标题。"), action("exit")]),
        due,
        epoch,
        seconds,
        millis,
        reminder,
        post,
        result,
        *condition(result, success,
                   [action("showresult", Text=token_text("苹果提醒已创建。飞书提交失败，返回码：", result))],
                   matches="0"),
    ]
    return workflow("新增必做（可同步）", actions, credential)


def workflow(name, actions, credential):
    return {
        "WFWorkflowName": name,
        "WFWorkflowClientVersion": "4018.0.4",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {"WFWorkflowIconStartColor": 1440408063, "WFWorkflowIconGlyphNumber": 59511},
        "WFWorkflowActions": actions,
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowImportQuestions": [{
            "ActionIndex": actions.index(credential),
            "Category": "Parameter",
            "ParameterKey": "WFTextActionText",
            "Text": "输入你自己的飞书多维表格授权码",
            "DefaultValue": TOKEN_PLACEHOLDER,
        }],
        "WFWorkflowTypes": [],
        "WFQuickActionSurfaces": [],
        "WFWorkflowHasShortcutInputVariables": False,
    }


def find_reminders(completed):
    return output_action(
        "filter.reminders", "已完成的关联提醒" if completed else "未完成的关联提醒",
        WFContentItemInputParameter="Library",
        WFContentItemFilter={
            "WFSerializationType": "WFContentPredicateTableTemplate",
            "Value": {
                "WFActionParameterFilterPrefix": 1,
                "WFContentPredicateBoundedDate": False,
                "WFActionParameterFilterTemplates": [
                    {"Property": "Notes", "Operator": 99, "Removable": True,
                     "Values": {"String": token_text(RECORD_NOTE)}},
                    {"Property": "Is Completed", "Operator": 4, "Removable": True,
                     "Values": {"Bool": completed}},
                ],
            },
        },
    )


def sync_reminders(credential, endpoint, completed):
    reminders = find_reminders(completed)
    group = str(uuid.uuid4()).upper()
    repeat_item = {"WFSerializationType": "WFTextTokenAttachment",
                   "Value": {"Type": "Variable", "VariableName": "Repeat Item"}}
    notes = output_action("properties.reminders", "提醒备注", WFInput=repeat_item,
                          WFContentItemPropertyName="Notes")
    ids = output_action("text.match", "飞书记录 ID", text=token_text(source=notes),
                        WFMatchTextPattern=r"(?m)(?<=^飞书记录：)rec[A-Za-z0-9]+(?=$)")
    count = output_action("count", "匹配数", Input=attachment(ids), WFCountType="Items")
    url = token_text(endpoint + "/", ids)
    response = request("飞书记录响应", credential, url, "GET")
    code = value(response, "code", "读取返回码")
    data = value(response, "data")
    record = value(data, "record")
    fields = value(record, "fields")
    keys = output_action("getvalueforkey", "飞书字段名", WFInput=attachment(fields),
                         WFGetDictionaryValueType="All Keys")
    checkbox = value(fields, COMPLETED_FIELD, "飞书完成状态")
    checked = output_action("text.match", "飞书已勾选", text=token_text(source=checkbox),
                            WFMatchTextPattern=r"(?i)^\s*(true|1|yes|是)\s*$")

    if completed:
        checked_payload = record_fields(item(
            COMPLETED_FIELD,
            {"WFSerializationType": "WFNumberSubstitutableState", "Value": True},
            item_type=4,
        ))
        def mark_done():
            update = request("写入完成状态", credential, url, "PUT", checked_payload)
            update_code = value(update, "code", "写入返回码")
            return [update, update_code, *condition(
                update_code, [], [action("showresult", Text=token_text("飞书写入失败，返回码 ", update_code)),
                                  action("exit")], matches="0")]

        reconcile = condition(keys, [checkbox, checked, *condition(checked, mark_done())],
                              mark_done(), contains=COMPLETED_FIELD)
    else:
        mark_done = action("setters.reminders", Mode="Set", WFInput=repeat_item,
                           WFContentItemPropertyName="Is Completed", WFReminderContentItemIsCompleted=True)
        reconcile = condition(keys, [checkbox, checked, *condition(checked, [], [mark_done])],
                              contains=COMPLETED_FIELD)

    return [
        reminders,
        action("repeat.each", GroupingIdentifier=group, WFControlFlowMode=0, WFInput=attachment(reminders)),
        notes, ids, count,
        *condition(count, [response, code, *condition(code, [data, record, fields, keys, *reconcile],
                    matches="0")], matches="1"),
        action("repeat.each", GroupingIdentifier=group, WFControlFlowMode=2),
    ]


def make_sync_shortcut(endpoint):
    credential = output_action("gettext", "飞书授权码", WFTextActionText=TOKEN_PLACEHOLDER)
    actions = [
        action("comment", WFCommentActionText="同步已关联的必做任务。只同步勾选完成。"),
        credential,
        *condition(credential, [action("showresult", Text="请先填入飞书多维表格授权码。"), action("exit")],
                   matches=TOKEN_PLACEHOLDER),
        *sync_reminders(credential, endpoint, False),
        *sync_reminders(credential, endpoint, True),
    ]
    return workflow("同步必做状态", actions, credential)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--variant", choices=("create", "sync"), required=True)
    parser.add_argument("--base-token", required=True, help="飞书多维表格 /base/ 后的标识")
    parser.add_argument("--table-id", required=True, help="链接中 table= 后的 tbl… 标识")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.base_token) or args.base_token.startswith("pt-"):
        parser.error("--base-token 应填写多维表格标识")
    if not re.fullmatch(r"tbl[A-Za-z0-9]+", args.table_id):
        parser.error("--table-id 应填写 tbl 开头的数据表 ID")
    endpoint = (
        "https://base-api.feishu.cn/open-apis/bitable/v1/apps/"
        f"{args.base_token}/tables/{args.table_id}/records"
    )
    build = make_create_shortcut if args.variant == "create" else make_sync_shortcut
    shortcut = build(endpoint)
    args.output.write_bytes(plistlib.dumps(shortcut, fmt=plistlib.FMT_BINARY, sort_keys=False))


if __name__ == "__main__":
    main()
